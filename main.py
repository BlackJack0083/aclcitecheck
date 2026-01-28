import argparse
import json
import logging
import os
import re
import time
from pathlib import Path

import bibtexparser
import requests
from dotenv import load_dotenv
from rapidfuzz import fuzz

# 加载 .env 环境变量
load_dotenv()

# ================= 配置区域 =================
# [cite_start]论文中推荐的相似度阈值 (0.9 = 90%) [cite: 108]
SIMILARITY_THRESHOLD = 90.0
# API 速率限制缓冲 (秒)
API_DELAY = 1.0
# 用户邮箱 (从 .env 获取)，用于 OpenAlex 的 Polite Pool
USER_EMAIL = os.getenv("OPENALEX_EMAIL")
# ===========================================

# 配置日志
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class CitationVerifier:
    def __init__(self):
        self.headers = {"User-Agent": f"mailto:{USER_EMAIL}"} if USER_EMAIL else {}

    def _search_dblp(self, title: str) -> dict | None:
        """策略A: 使用 DBLP 搜索 (CS领域最准)"""
        url = "https://dblp.org/search/publ/api"
        params = {"q": title, "format": "json", "h": 1}
        try:
            resp = requests.get(url, params=params, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                hits = data.get("result", {}).get("hits", {}).get("hit", [])
                if hits:
                    info = hits[0]["info"]
                    # DBLP 作者格式清洗
                    authors_raw = info.get("authors", {}).get("author", [])
                    if isinstance(authors_raw, dict):
                        authors_raw = [authors_raw]
                    elif isinstance(authors_raw, str):
                        authors_raw = [{"text": authors_raw}]

                    authors = [
                        a["text"] if isinstance(a, dict) else str(a)
                        for a in authors_raw
                    ]

                    return {
                        "source": "DBLP",
                        "title": info.get("title", ""),
                        "year": info.get("year", "N/A"),
                        "authors": authors,
                        "url": info.get("url", ""),
                    }
        except Exception as e:
            logger.warning(f"DBLP lookup failed: {e}")
        return None

    def _search_openalex(self, title: str) -> dict | None:
        """策略B: 使用 OpenAlex 搜索 (覆盖面更广)"""
        url = "https://api.openalex.org/works"
        params = {
            "search": title,
            "per-page": 1,
            "select": "display_name,publication_year,authorships,doi",
        }
        try:
            resp = requests.get(url, headers=self.headers, params=params, timeout=10)
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                if results:
                    top = results[0]
                    authors = [
                        a.get("author", {}).get("display_name", "")
                        for a in top.get("authorships", [])
                    ]
                    return {
                        "source": "OpenAlex",
                        "title": top.get("display_name", ""),
                        "year": top.get("publication_year", "N/A"),
                        "authors": authors,
                        "url": top.get("doi", ""),
                    }
        except Exception as e:
            logger.warning(f"OpenAlex lookup failed: {e}")
        return None

    def verify(self, title: str) -> dict | None:
        # 1. 尝试 DBLP
        result = self._search_dblp(title)
        if result:
            if fuzz.ratio(title.lower(), result["title"].lower()) < 70:
                logger.info("DBLP match low confidence, trying OpenAlex...")
            else:
                return result
        # 2. 尝试 OpenAlex
        time.sleep(API_DELAY)
        return self._search_openalex(title)


def scan_tex_files(input_path: str) -> set[str]:
    """递归扫描 .tex 文件提取引用 Key"""
    path = Path(input_path)
    # 核心修改：如果是目录则递归查找，如果是文件则直接列表
    tex_files = list(path.rglob("*.tex")) if path.is_dir() else [path]

    unique_keys = set()
    citation_pattern = r"\\cite[a-zA-Z]*\*?\{([^{}]+)\}"

    logger.info(f"Scanning {len(tex_files)} .tex files in '{input_path}'...")

    for tex_file in tex_files:
        try:
            with open(tex_file, encoding="utf-8") as f:
                content = f.read()
                content = re.sub(r"(?<!\\)%.*", "", content)  # 去注释
                matches = re.findall(citation_pattern, content)
                for match in matches:
                    keys = [k.strip() for k in match.split(",")]
                    unique_keys.update(keys)
        except Exception as e:
            logger.error(f"Error reading {tex_file}: {e}")

    logger.info(f"Found {len(unique_keys)} unique citation keys.")
    return unique_keys


def parse_bib_files(bib_input: str) -> dict:
    """
    核心修改：递归扫描 .bib 文件并合并为一个大字典
    """
    path = Path(bib_input)
    # 如果是目录则递归查找 *.bib，如果是文件则直接处理
    bib_files = list(path.rglob("*.bib")) if path.is_dir() else [path]

    master_bib_map = {}
    logger.info(f"Parsing {len(bib_files)} .bib files from '{bib_input}'...")

    for bib_file in bib_files:
        try:
            with open(bib_file, encoding="utf-8") as f:
                bib_db = bibtexparser.load(f)

            for entry in bib_db.entries:
                raw_title = entry.get("title", "")
                clean_title = re.sub(r"[\{\}\n]", "", raw_title).strip()
                clean_author = entry.get("author", "").replace("\n", " ")

                # 如果有重复 Key，后读取的会覆盖先读取的 (通常这是预期行为)
                master_bib_map[entry["ID"]] = {
                    "key": entry["ID"],
                    "title": clean_title,
                    "author": clean_author,
                    "year": entry.get("year", "N/A"),
                    "source_file": str(bib_file.name),  # 记录一下来源文件名，方便调试
                    "raw_entry": entry,
                }
        except Exception as e:
            logger.error(f"Error parsing bib file {bib_file}: {e}")

    logger.info(f"Merged {len(master_bib_map)} entries from all BibTeX files.")
    return master_bib_map


def main():
    parser = argparse.ArgumentParser(
        description="Citation Hallucination Checker (DBLP + OpenAlex)"
    )

    # 使用 nargs='?' 配合 default，实现"有参数读参数，没参数读默认"
    parser.add_argument(
        "input_path",
        nargs="?",
        default="./temp/tex",
        help="Folder containing .tex files or path to a single .tex file",
    )

    parser.add_argument(
        "bib_input",
        nargs="?",
        default="./temp/bib",
        help="Folder containing .bib files or path to a single .bib file",
    )

    args = parser.parse_args()

    # 1. 准备输出目录
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    # 2. 扫描引用 Key (支持文件夹)
    tex_keys = scan_tex_files(args.input_path)
    if not tex_keys:
        print("⚠️ No citation keys found. Exiting.")
        return

    # 3. 解析 Bib 数据 (支持文件夹，自动合并)
    bib_data = parse_bib_files(args.bib_input)
    if not bib_data:
        print("⚠️ No BibTeX entries found. Exiting.")
        return

    verifier = CitationVerifier()

    all_citations_report = []
    hallucination_report = []

    print("\n🚀 Starting Verification Loop...")

    for idx, key in enumerate(tex_keys):
        # ... (后续验证逻辑保持不变)
        citation_info = {
            "key": key,
            "status": "Verified",
            "bib_metadata": bib_data.get(key, None),
            "verification_result": None,
        }

        # Case 0: Missing in Bib
        if key not in bib_data:
            citation_info["status"] = "Missing in Bib"
            hallucination_report.append(
                {
                    "key": key,
                    "reason": "Citation key found in TeX but missing in .bib files",
                }
            )
            all_citations_report.append(citation_info)
            continue

        title = bib_data[key]["title"]
        print(f"[{idx+1}/{len(tex_keys)}] Checking: {key}...", end="\r")

        # 4. 联网验证
        match_result = verifier.verify(title)

        if not match_result:
            citation_info["status"] = "Not Found"
            hallucination_report.append(
                {
                    "key": key,
                    "bib_title": title,
                    "reason": "Paper not found in DBLP or OpenAlex",
                    "risk_level": "High",
                }
            )
        else:
            citation_info["verification_result"] = match_result
            found_title = match_result["title"]
            score = fuzz.ratio(title.lower(), found_title.lower())

            if score < SIMILARITY_THRESHOLD:
                citation_info["status"] = "Title Mismatch"
                hallucination_report.append(
                    {
                        "key": key,
                        "bib_title": title,
                        "found_title": found_title,
                        "similarity_score": score,
                        "source": match_result["source"],
                        "reason": "Title similarity below threshold",
                        "risk_level": "Medium",
                    }
                )
            else:
                bib_author_first = (
                    bib_data[key]["author"].split(",")[0].split(" and ")[0].strip()
                )
                found_authors = match_result["authors"]
                author_match = any(
                    fuzz.partial_ratio(bib_author_first.lower(), fa.lower()) > 80
                    for fa in found_authors
                )

                if not author_match:
                    citation_info["status"] = "Author Mismatch"
                    hallucination_report.append(
                        {
                            "key": key,
                            "bib_author": bib_data[key]["author"],
                            "found_authors": found_authors,
                            "reason": "First author mismatch",
                            "risk_level": "Medium",
                        }
                    )

        all_citations_report.append(citation_info)

    print("\n" + "=" * 50)

    # 5. 输出 JSON 文件
    with open(output_dir / "all_citations.json", "w", encoding="utf-8") as f:
        json.dump(all_citations_report, f, indent=2, ensure_ascii=False)

    if hallucination_report:
        with open(output_dir / "hallucination_report.json", "w", encoding="utf-8") as f:
            json.dump(hallucination_report, f, indent=2, ensure_ascii=False)
        print(
            f"🚨 FOUND {len(hallucination_report)} ISSUES. Check output/hallucination_report.json"
        )
    else:
        print("✅ No hallucinations found.")

    print(f"📂 Full report saved to {output_dir}/all_citations.json")


if __name__ == "__main__":
    main()
