from pathlib import Path
from playwright.sync_api import sync_playwright


BASE_URL = "http://localhost:8503"
OUTPUT_DIR = Path("tests") / "artifacts"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def open_page(page, path: str):
    page.goto(f"{BASE_URL}/{path}", wait_until="networkidle")
    page.wait_for_timeout(1500)


def save(page, name: str):
    page.screenshot(path=str(OUTPUT_DIR / f"{name}.png"), full_page=True)


def main():
    steps = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1400})
        open_page(page, "")
        save(page, "01_home")
        steps.append(("home", page.locator("body").inner_text()[:300]))

        open_page(page, "因子输入")
        save(page, "02_factor_input")
        steps.append(("factor_input", page.locator("body").inner_text()[:500]))

        page_paths = [
            ("03_traditional_eval", "传统评估"),
            ("04_压力测试", "压力测试"),
            ("05_重复性检测", "重复性检测"),
            ("06_适用性地图", "适用性地图"),
            ("07_报告与凭证", "报告与凭证"),
        ]
        for filename, path in page_paths:
            open_page(page, path)
            save(page, filename)
            steps.append((path, page.locator("body").inner_text()[:500]))

        browser.close()

    report = OUTPUT_DIR / "smoke_full_flow.txt"
    lines = []
    for name, text in steps:
        lines.append(f"## {name}")
        lines.append(text)
        lines.append("")
    report.write_text("\n".join(lines), encoding="utf-8")
    print(str(report))


if __name__ == "__main__":
    main()
