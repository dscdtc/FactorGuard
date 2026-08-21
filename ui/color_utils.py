"""
颜色方案工具
"""
from config import COLOR_PASS, COLOR_WARN, COLOR_FAIL, COLOR_NEUTRAL, COLOR_UNTESTED

# 颜色方案
COLOR_SCHEME = {
    "pass": COLOR_PASS,       # "#176c49"
    "warn": COLOR_WARN,       # "#d49b2e"
    "fail": COLOR_FAIL,       # "#a53c3c"
    "neutral": COLOR_NEUTRAL, # "#2267a5"
    "untested": COLOR_UNTESTED, # "#b8c2ca"
    "bg": "#f8f9fa",
    "card_bg": "#ffffff"
}


def get_verdict_color(verdict: str) -> str:
    """根据结论返回颜色"""
    mapping = {
        "invalid": COLOR_FAIL,
        "insufficient": COLOR_WARN,
        "fragile": COLOR_WARN,
        "conditional": COLOR_NEUTRAL,
        "supported": COLOR_PASS,
    }
    return mapping.get(verdict, COLOR_UNTESTED)


def get_evidence_color(level: str) -> str:
    """根据证据等级返回颜色"""
    mapping = {
        "strong": COLOR_PASS,
        "moderate": COLOR_NEUTRAL,
        "weak": COLOR_WARN,
        "none": COLOR_UNTESTED,
        "contradictory": COLOR_FAIL,
    }
    return mapping.get(level, COLOR_UNTESTED)


def get_heatmap_colorscale():
    """返回热力图颜色映射"""
    return [
        [0.0, COLOR_FAIL],
        [0.25, COLOR_WARN],
        [0.5, COLOR_UNTESTED],
        [0.75, COLOR_NEUTRAL],
        [1.0, COLOR_PASS],
    ]