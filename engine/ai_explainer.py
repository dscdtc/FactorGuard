"""
AI 解释模块 - 纯 Python 实现，不依赖外部 API。

功能：
- parse_text_to_spec: 自然语言 → 结构化因子定义（关键词匹配 + 模板规则）
- generate_evidence_summary: 生成证据化总结（模板化输出）
- generate_next_test_suggestion: 生成下一步测试建议
- fallback_analysis: 完全模板化的分析结果（AI 不可用时的降级方案）
"""

import re
import random
from typing import Optional, Any

from config import COLOR_PASS, COLOR_WARN, COLOR_FAIL, COLOR_NEUTRAL, COLOR_UNTESTED
from models.factor_spec import FactorSpec

# ============================================================
# 关键词 → 类别映射
# ============================================================

CATEGORY_KEYWORDS = {
    "动量": ["动量", "momentum", "趋势跟踪", "趋势追踪", "惯性"],
    "反转": ["反转", "均值回归", "逆势", "反向", "reverse", "mean_reversion"],
    "趋势": ["趋势", "trend", "均线", "金叉", "死叉", "突破"],
    "波动率": ["波动", "波动率", "volatility", "波幅", "振幅"],
    "成交量": ["成交量", "量价", "换手", "volume", "放量", "缩量"],
    "价值": ["价值", "value", "估值", "市盈率", "市净率", "pe", "pb", "股息率"],
    "质量": ["质量", "quality", "roe", "roa", "毛利率", "净利率", "资产负债率"],
    "规模": ["规模", "市值", "size", "大盘", "小盘", "中盘"],
    "情绪": ["情绪", "sentiment", "舆情", "新闻", "分析师"],
    "成长": ["成长", "growth", "增速", "增长", "同比增长"],
    "流动性": ["流动性", "liquidity", "冲击成本", "买卖价差"],
}

# ============================================================
# 关键词 → 公式模板
# ============================================================

FORMULA_TEMPLATES = {
    "收益": ("delay(close, 1) / delay(close, {window}) - 1", "close"),
    "涨幅": ("delay(close, 1) / delay(close, {window}) - 1", "close"),
    "回报": ("delay(close, 1) / delay(close, {window}) - 1", "close"),
    "收益率": ("delay(close, 1) / delay(close, {window}) - 1", "close"),
    "成交量": ("ts_mean(volume, {window})", "volume"),
    "换手": ("ts_mean(turnover_rate, {window})", "turnover_rate"),
    "波动": ("ts_std(delay(close, 1) / delay(close, 2) - 1, {window})", "close"),
    "均线": ("ts_mean(close, {window})", "close"),
    "突破": ("close / ts_max(close, {window}) - 1", "close"),
    "振幅": ("(ts_max(high, {window}) - ts_min(low, {window})) / ts_mean(close, {window})", "high"),
    "量比": ("volume / ts_mean(volume, {window})", "volume"),
    "市值": ("total_mv", "total_mv"),
    "市盈率": ("pe_ttm", "pe_ttm"),
}


# ============================================================
# 默认参数
# ============================================================

DEFAULT_WINDOW = 20


# ============================================================
# 1. parse_text_to_spec
# ============================================================

def parse_text_to_spec(text: str) -> dict:
    """将自然语言描述转为结构化因子定义（模板降级方案）。

    使用关键词匹配 + 模板规则，不依赖 LLM 调用。

    Parameters
    ----------
    text : str
        自然语言因子描述，如 "20日动量因子，计算过去20个交易日的收益率"

    Returns
    -------
    dict
        包含 name_cn, formula, formula_cn, category, expected_direction,
        params, inputs, rationale_cn 等字段
    """
    text_lower = text.lower()

    # ---- 提取因子名称 ----
    name_cn = _extract_name(text)

    # ---- 提取窗口参数 ----
    window = _extract_window(text)

    # ---- 推测类别 ----
    category = _infer_category(text)

    # ---- 推测预期方向 ----
    direction = _infer_direction(text)

    # ---- 推测公式和输入 ----
    formula, inputs = _infer_formula(text, window)

    # ---- 推测公式中文描述 ----
    formula_cn = _infer_formula_cn(text, category, window)

    # ---- 推测逻辑依据 ----
    rationale_cn = _infer_rationale(category, direction)

    return {
        "name_cn": name_cn,
        "formula": formula,
        "formula_cn": formula_cn,
        "category": category,
        "expected_direction": direction,
        "params": {"window": window},
        "inputs": inputs,
        "rationale_cn": rationale_cn,
    }


def _extract_name(text: str) -> str:
    """从文本中提取因子名称"""
    # 尝试匹配 "XX因子" 模式
    m = re.search(r"([\u4e00-\u9fa5a-zA-Z0-9]+(?:因子|指标|模型))", text)
    if m:
        return m.group(1)
    # 尝试匹配句首主题
    m = re.search(r"^([\u4e00-\u9fa5a-zA-Z0-9]+)(?:，|,|。)", text)
    if m:
        return m.group(1) + "因子"
    return "自定义因子"


def _extract_window(text: str) -> int:
    """从文本中提取窗口参数（数值）"""
    # 匹配 "N日"、"N个交易日"、"N天" 等
    m = re.search(r"(\d+)\s*(?:日|个交易日|天)", text)
    if m:
        return int(m.group(1))
    # 匹配 "N周"、"N月"
    m = re.search(r"(\d+)\s*周", text)
    if m:
        return int(m.group(1)) * 5
    m = re.search(r"(\d+)\s*月", text)
    if m:
        return int(m.group(1)) * 21
    return DEFAULT_WINDOW


def _infer_category(text: str) -> str:
    """根据关键词推测因子类别"""
    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in text.lower():
                return category
    return "其他"


def _infer_direction(text: str) -> str:
    """根据关键词推测预期方向"""
    # 做多/多头/买入 → higher
    long_patterns = ["做多", "高收益", "买入", "long", "多头", "看多", "higher"]
    for p in long_patterns:
        if p.lower() in text.lower():
            return "higher"
    # 做空/空头/卖出 → lower
    short_patterns = ["做空", "卖出", "short", "空头", "看空", "lower"]
    for p in short_patterns:
        if p.lower() in text.lower():
            return "lower"
    # 反转类默认 lower
    if "反转" in text or "reverse" in text.lower():
        return "lower"
    return "higher"


def _infer_formula(text: str, window: int) -> tuple:
    """根据关键词推测公式和输入字段"""
    # 按优先级匹配模板
    for keyword, (template, field) in FORMULA_TEMPLATES.items():
        if keyword in text:
            formula = template.format(window=window) if "{window}" in template else template
            return formula, [field]

    # 默认：收益率变化
    formula = f"delay(close, 1) / delay(close, {window}) - 1"
    return formula, ["close"]


def _infer_formula_cn(text: str, category: str, window: int) -> str:
    """推测公式的中文描述"""
    # 直接提取文本中描述计算过程的部分
    m = re.search(r"(?:计算|衡量|度量|刻画)([\u4e00-\u9fa5a-zA-Z0-9，,、；;。]+)", text)
    if m:
        return f"计算{m.group(1)}"

    # 根据类别生成描述
    category_descriptions = {
        "动量": f"计算过去{window}个交易日的价格变化率，衡量价格趋势强度",
        "反转": f"计算过去{window}个交易日的价格变化率，捕捉均值回归特征",
        "趋势": f"基于过去{window}个交易日的价格数据，构建趋势跟踪信号",
        "波动率": f"计算过去{window}个交易日的价格波动幅度",
        "成交量": f"统计过去{window}个交易日的成交量特征",
        "价值": f"基于估值指标构建价值因子",
        "质量": f"基于财务质量指标构建质量因子",
        "规模": f"基于市值规模构建规模因子",
        "情绪": f"基于市场情绪指标构建情绪因子",
        "成长": f"基于增长率指标构建成长因子",
        "流动性": f"基于流动性指标构建流动性因子",
    }
    return category_descriptions.get(category, f"基于过去{window}个交易日的数据计算因子值")


def _infer_rationale(category: str, direction: str) -> str:
    """推测因子的逻辑依据"""
    rationales = {
        "动量": {
            "higher": "基于动量效应，过去表现好的股票未来短期内可能继续表现优异，投资者反应不足导致价格趋势延续",
            "lower": "基于动量效应衰减，过度上涨后存在回调压力，短期涨幅过大的股票面临获利了结风险",
        },
        "反转": {
            "higher": "基于均值回归理论，超跌股票存在反弹动力，市场过度反应后价格向均值回归",
            "lower": "基于均值回归理论，过度上涨的股票面临回调压力，价格将向均值回归",
        },
        "趋势": {
            "higher": "基于趋势跟踪策略，价格突破关键位置后趋势延续概率较高，顺势而为获取收益",
            "lower": "基于趋势突破策略，向下突破关键支撑位后跌势延续，及时止损控制风险",
        },
        "波动率": {
            "higher": "高波动率股票存在更大的定价偏差机会，在市场波动中更容易出现超额收益",
            "lower": "低波动率异常现象，低波动股票的风险调整后收益反而优于高波动股票",
        },
        "成交量": {
            "higher": "放量上涨表明资金持续流入，成交量放大伴随价格上涨是强势信号",
            "lower": "缩量下跌表明抛压不足，成交量萎缩是底部特征，后续可能反弹",
        },
        "价值": {
            "higher": "基于价值投资理念，低估值股票长期来看具有更高的安全边际和上涨空间",
            "lower": "价值陷阱风险，极度低估可能反映基本面恶化，需警惕低估值背后的风险",
        },
        "质量": {
            "higher": "高质量公司具有更强的盈利能力、更健康的资产负债表和更可持续的竞争优势",
            "lower": "质量因子短期失效时，高质量公司可能因估值过高而面临回调风险",
        },
        "规模": {
            "higher": "小盘股效应，小市值公司成长空间更大，在市场上涨阶段弹性更强",
            "lower": "大盘股防御性更强，在市场下跌阶段大盘蓝筹抗跌能力突出",
        },
        "情绪": {
            "higher": "正面市场情绪推动股价上涨，乐观情绪扩散带来增量资金入场",
            "lower": "负面情绪蔓延导致恐慌性抛售，市场悲观时往往出现超跌机会",
        },
        "成长": {
            "higher": "高成长公司具有更高的盈利增长预期，市场愿意给予更高的估值溢价",
            "lower": "成长股估值过高时存在回调风险，增长不及预期将导致戴维斯双杀",
        },
        "流动性": {
            "higher": "高流动性股票交易成本低，大资金进出方便，更受机构投资者青睐",
            "lower": "低流动性股票存在流动性溢价，补偿投资者承担的流动性风险",
        },
    }

    default_rationale = {
        "higher": "基于量化分析，该因子在历史上表现出正向预测能力，做多高因子值股票可获得超额收益",
        "lower": "基于量化分析，该因子在历史上表现出反向预测能力，做空高因子值股票可获得超额收益",
    }

    cat_rationales = rationales.get(category, default_rationale)
    return cat_rationales.get(direction, default_rationale.get(direction, "基于量化分析方法构建的因子"))


# ============================================================
# 2. generate_evidence_summary
# ============================================================

def generate_evidence_summary(
    factor_spec: FactorSpec,
    evaluation_results: dict,
) -> str:
    """生成证据化总结（模板降级方案）。

    Parameters
    ----------
    factor_spec : FactorSpec
        因子规格对象
    evaluation_results : dict
        评估结果字典，预期包含 IC/RankIC/压力测试/适用性等关键指标

    Returns
    -------
    str
        自然语言总结文本
    """
    lines: list[str] = []

    # ---- 标题 ----
    lines.append(f"## {factor_spec.name_cn} 因子证据化评估报告")
    lines.append("")

    # ---- 1. 因子基本信息 ----
    lines.append("### 一、因子基本信息")
    lines.append("")
    lines.append(f"- **因子名称**：{factor_spec.name_cn}（{factor_spec.name}）")
    lines.append(f"- **因子类别**：{factor_spec.category}")
    lines.append(f"- **因子公式**：{factor_spec.formula_cn or factor_spec.formula or '未指定'}")
    lines.append(f"- **预期方向**：{'做多高因子值' if factor_spec.expected_direction == 'higher' else '做空高因子值'}")
    if factor_spec.rationale_cn:
        lines.append(f"- **逻辑依据**：{factor_spec.rationale_cn}")
    lines.append("")

    # ---- 2. IC/RankIC 核心指标 ----
    lines.append("### 二、IC 分析")
    lines.append("")

    ic_mean = evaluation_results.get("ic_mean")
    ic_ir = evaluation_results.get("ic_ir")
    rank_ic_mean = evaluation_results.get("rank_ic_mean")
    rank_ic_ir = evaluation_results.get("rank_ic_ir")
    ic_pos_ratio = evaluation_results.get("ic_pos_ratio")
    ic_std = evaluation_results.get("ic_std")

    if ic_mean is not None:
        _append_ic_analysis(lines, ic_mean, ic_ir, rank_ic_mean, rank_ic_ir,
                            ic_pos_ratio, ic_std, factor_spec.expected_direction)
    else:
        # 从 precomputed 指标中推断
        lines.append("当前评估数据中未包含完整 IC 序列，以下为可用指标：")
        lines.append("")
        _append_available_metrics(lines, evaluation_results)

    lines.append("")

    # ---- 3. 压力测试 ----
    lines.append("### 三、压力测试结论")
    lines.append("")
    _append_stress_test_section(lines, evaluation_results)
    lines.append("")

    # ---- 4. 适用性评估 ----
    lines.append("### 四、适用性评估")
    lines.append("")
    _append_suitability_section(lines, evaluation_results, factor_spec)
    lines.append("")

    # ---- 5. 风险提示 ----
    lines.append("### 五、风险提示")
    lines.append("")
    _append_risk_section(lines, factor_spec, evaluation_results)
    lines.append("")

    # ---- 总结 ----
    lines.append("---")
    lines.append(f"*本报告由 FactorGuard 因子验真引擎自动生成，生成时间基于模板化规则。*")
    lines.append(f"*当 AI 接口可用时，可使用 generate_evidence_summary 的 LLM 增强版本获得更深入的分析。*")

    return "\n".join(lines)


def _append_ic_analysis(
    lines: list,
    ic_mean: float,
    ic_ir: Optional[float],
    rank_ic_mean: Optional[float],
    rank_ic_ir: Optional[float],
    ic_pos_ratio: Optional[float],
    ic_std: Optional[float],
    expected_direction: str,
) -> None:
    """添加 IC 分析段落"""
    direction_label = "正向" if expected_direction == "higher" else "反向"

    # IC 均值解读
    abs_ic = abs(ic_mean)
    if abs_ic >= 0.05:
        ic_strength = "非常显著"
        ic_comment = f"因子{expected_direction == 'higher' and '多' or '空'}头端具有稳健的预测能力"
    elif abs_ic >= 0.03:
        ic_strength = "较为显著"
        ic_comment = f"因子具备一定的{direction_label}预测能力，可作为多因子体系的有效补充"
    elif abs_ic >= 0.01:
        ic_strength = "边际显著"
        ic_comment = "因子预测能力有限，建议结合其他因子共同使用"
    else:
        ic_strength = "不显著"
        ic_comment = "因子在当前样本区间内预测能力较弱，需关注参数优化或市场环境变化"

    lines.append(f"| 指标 | 数值 | 解读 |")
    lines.append(f"|------|------|------|")
    lines.append(f"| IC 均值 | {ic_mean:.4f} | {ic_strength}，{ic_comment} |")

    if ic_std is not None:
        lines.append(f"| IC 标准差 | {ic_std:.4f} | {'IC 波动较小，稳定性好' if ic_std < 0.06 else 'IC 波动较大，需关注稳定性'} |")

    if ic_ir is not None:
        ir_quality = "优秀" if ic_ir >= 0.5 else ("良好" if ic_ir >= 0.3 else "一般")
        lines.append(f"| IC_IR | {ic_ir:.4f} | 信息比率{ir_quality}，{'因子稳定性值得信赖' if ic_ir >= 0.3 else '因子稳定性有待提升'} |")

    if ic_pos_ratio is not None:
        lines.append(f"| IC 胜率 | {ic_pos_ratio:.1%} | {'方向一致性高' if ic_pos_ratio >= 0.55 else '方向一致性一般'} |")

    if rank_ic_mean is not None:
        lines.append(f"| Rank IC 均值 | {rank_ic_mean:.4f} | 排序相关性 |")

    if rank_ic_ir is not None:
        lines.append(f"| Rank IC_IR | {rank_ic_ir:.4f} | 排序信息比率 |")


def _append_available_metrics(lines: list, results: dict) -> None:
    """添加可用指标信息"""
    display_metrics = {
        "ic_mean_5d": "IC 均值（5日）",
        "icir_5d": "ICIR（5日）",
        "coverage": "覆盖率",
        "turnover": "换手率",
        "status": "验证状态",
    }
    for key, label in display_metrics.items():
        val = results.get(key)
        if val is not None:
            lines.append(f"- **{label}**：{val}")


def _append_stress_test_section(lines: list, results: dict) -> None:
    """添加压力测试段落"""
    stress_tests = results.get("stress_tests", {})
    stress_passed = results.get("stress_passed", 0)
    stress_total = results.get("stress_total", 0)

    if stress_tests:
        for test_name, test_result in stress_tests.items():
            if isinstance(test_result, dict):
                status = test_result.get("status", "unknown")
                value = test_result.get("value", "")
                icon = "✅" if status == "pass" else ("⚠️" if status == "warn" else "❌")
                lines.append(f"- {icon} **{test_name}**：{value}")
            else:
                lines.append(f"- **{test_name}**：{test_result}")
    elif stress_total > 0:
        lines.append(f"压力测试综合结果：{stress_passed}/{stress_total} 项通过")
        if stress_passed == stress_total:
            lines.append("所有压力测试项目均通过，因子在不同市场环境下表现稳健。")
        elif stress_passed >= stress_total * 0.7:
            lines.append("大部分压力测试通过，部分场景下因子表现存在波动，建议关注。")
        else:
            lines.append("多项压力测试未通过，因子在极端市场环境下可能存在失效风险，建议谨慎使用。")
    else:
        lines.append("当前暂无压力测试数据。")
        lines.append("")
        lines.append("建议执行的标准化压力测试包括：")
        lines.append("- 牛熊市分段表现对比")
        lines.append("- 极端行情（如2015年股灾、2020年疫情）回测")
        lines.append("- 不同市值分组下的因子表现")
        lines.append("- 行业轮动环境下的因子稳定性")


def _append_suitability_section(lines: list, results: dict, factor_spec: FactorSpec) -> None:
    """添加适用性评估段落"""
    # 市场环境适用性
    lines.append("**市场环境适用性：**")
    lines.append("")

    category = factor_spec.category
    suitability_map = {
        "动量": "在趋势市中表现优异，震荡市中可能频繁产生假信号。适合单边上涨行情，在横盘整理阶段需谨慎使用。",
        "反转": "在震荡市中表现突出，趋势市中可能持续亏损。适合市场波动率适中、缺乏明确方向的阶段。",
        "趋势": "在趋势明确的行情中效果最佳，盘整期可能产生较多假突破信号。建议结合趋势过滤器使用。",
        "波动率": "在高波动环境中信号更丰富，低波动时期因子区分度下降。极端行情下需注意尾部风险。",
        "成交量": "在放量行情中信号可靠度更高，缩量阶段有效性下降。适合结合价格因子形成量价配合策略。",
        "价值": "在价值风格占优阶段表现突出，成长风格主导时可能跑输。适合长期配置和均值回归策略。",
        "质量": "在市场风险偏好下降时防御性突出，牛市环境中弹性可能不足。适合作为组合的压舱石。",
        "规模": "小盘因子在流动性宽松时表现好，大盘因子在避险情绪升温时更受青睐。",
        "情绪": "在信息传播快速的市场环境中效果更好，需要高频数据支持。散户主导的市场中信号更有效。",
        "成长": "在流动性充裕、风险偏好高的环境中表现优异，加息周期中可能承压。",
        "流动性": "在市场流动性分化明显时效果显著，流动性危机时因子可能失效。",
    }
    lines.append(suitability_map.get(category, "建议持续跟踪因子在不同市场环境下的表现，积累更多样本后再做判断。"))
    lines.append("")

    # 持仓周期适用性
    lines.append("**持仓周期建议：**")
    lines.append("")
    window = factor_spec.params.get("window", 20) if factor_spec.params else 20
    if window <= 5:
        lines.append(f"因子窗口为 {window} 日，适合短线交易策略（1-5个交易日持仓周期）。")
    elif window <= 20:
        lines.append(f"因子窗口为 {window} 日，适合中短线策略（1-4周持仓周期）。")
    elif window <= 60:
        lines.append(f"因子窗口为 {window} 日，适合中线策略（1-3个月持仓周期）。")
    else:
        lines.append(f"因子窗口为 {window} 日，适合长线策略（3个月以上持仓周期）。")


def _append_risk_section(lines: list, factor_spec: FactorSpec, results: dict) -> None:
    """添加风险提示段落"""
    risks = []

    # 基于因子类别的风险
    category_risks = {
        "动量": [
            "动量崩溃风险：在市场急剧反转时，动量因子可能遭受大幅回撤",
            "拥挤交易风险：热门动量因子可能被过度交易，导致alpha衰减",
        ],
        "反转": [
            "趋势延续风险：在强趋势市场中，反转因子可能持续亏损",
            "价值陷阱风险：部分超跌股票可能因基本面恶化而持续下跌",
        ],
        "趋势": [
            "假突破风险：震荡市中频繁出现假突破信号，导致交易成本上升",
            "滞后性风险：趋势确认时可能已错过最佳入场时机",
        ],
        "波动率": [
            "尾部风险：极端波动事件下因子可能产生极端值，导致组合风险失控",
            "波动率聚集风险：高波动期聚集出现，因子区分度可能下降",
        ],
        "成交量": [
            "流动性陷阱：放量下跌时成交量信号可能产生误导",
            "操纵风险：小盘股中成交量可能被人为操纵",
        ],
        "价值": [
            "价值陷阱：低估值可能反映基本面恶化而非投资机会",
            "风格轮动风险：成长风格主导时价值因子可能长期跑输",
        ],
        "质量": [
            "估值过高风险：高质量公司可能因估值溢价过高而面临回调",
            "财务造假风险：财务指标可能被美化，需交叉验证",
        ],
        "规模": [
            "流动性风险：小盘股流动性不足，大资金进出困难",
            "壳价值退潮风险：注册制推进下小盘股壳价值持续下降",
        ],
        "情绪": [
            "噪声风险：市场情绪指标可能包含大量噪声，信号不稳定",
            "滞后性风险：情绪指标可能已经是价格的滞后反映",
        ],
        "成长": [
            "增长不及预期风险：高增长预期落空将导致估值和业绩双杀",
            "竞争加剧风险：行业高增长吸引竞争者进入，利润率承压",
        ],
        "流动性": [
            "流动性危机风险：市场系统性风险爆发时流动性可能瞬间枯竭",
            "策略容量风险：流动性因子策略容量有限，规模扩大后收益下降",
        ],
    }

    risks = category_risks.get(factor_spec.category, [
        "因子可能在某些市场环境下失效，建议持续监控",
        "历史回测不代表未来表现，实盘中需结合市场环境调整",
        "单一因子风险集中，建议纳入多因子框架使用",
    ])

    for i, risk in enumerate(risks, 1):
        lines.append(f"{i}. **{risk.split('：')[0] if '：' in risk else '风险提示'}**：{risk.split('：', 1)[1] if '：' in risk else risk}")

    # 通用风险
    lines.append("")
    lines.append("**通用风险提示：**")
    lines.append("- 历史表现不代表未来收益，因子有效性可能随市场环境变化而衰减")
    lines.append("- 实盘交易需考虑冲击成本、滑点、涨跌停限制等实际约束")
    lines.append("- 建议定期（每季度/每半年）对因子进行重新评估和参数校准")


# ============================================================
# 3. generate_next_test_suggestion
# ============================================================

def generate_next_test_suggestion(evaluation_results: dict) -> str:
    """生成下一个建议测试。

    Parameters
    ----------
    evaluation_results : dict
        评估结果字典

    Returns
    -------
    str
        建议的下一步测试描述
    """
    suggestions_pool = []

    # 检查已有的测试项，推测缺失的测试
    tested_items = set()

    stress_tests = evaluation_results.get("stress_tests", {})
    if stress_tests:
        for name in stress_tests:
            tested_items.add(name.lower())

    # 检查 IC 相关指标
    has_ic = "ic_mean" in evaluation_results or "ic_mean_5d" in evaluation_results
    has_rank_ic = "rank_ic_mean" in evaluation_results
    has_icir = "ic_ir" in evaluation_results or "icir_5d" in evaluation_results
    has_turnover = "turnover" in evaluation_results
    has_sector_neutral = any("行业" in k or "sector" in k.lower() for k in tested_items)
    has_style_neutral = any("风格" in k or "style" in k.lower() for k in tested_items)
    has_decay = any("衰减" in k or "decay" in k.lower() for k in tested_items)
    has_extreme = any("极端" in k or "extreme" in k.lower() or "股灾" in k or "疫情" in k for k in tested_items)
    has_cap = any("市值" in k or "cap" in k.lower() or "size" in k.lower() for k in tested_items)
    has_long_horizon = any("长周期" in k or "long" in k.lower() or "远期" in k for k in tested_items)

    # 基于缺失的测试生成建议
    if not has_sector_neutral:
        suggestions_pool.extend([
            "建议增加行业中性化测试，以排除行业暴露对因子收益的影响，确保因子alpha来源于个股选择而非行业配置",
            "建议对因子进行行业中性化处理，对比中性化前后的IC表现，评估行业偏离对因子收益的贡献度",
        ])

    if not has_style_neutral:
        suggestions_pool.extend([
            "建议增加风格中性化测试（市值、估值、动量等），以排除常见风格因子对收益的干扰",
            "建议使用Barra风格因子模型进行归因分析，判断因子是否存在显著的风格暴露",
        ])

    if not has_decay:
        suggestions_pool.extend([
            "建议在更长预测周期（如10日、20日）上验证信号衰减情况，确定因子的最优持仓周期",
            "建议绘制IC衰减曲线，分析因子预测能力随持仓周期延长的变化趋势，以便确定最佳换仓频率",
        ])

    if not has_extreme:
        suggestions_pool.extend([
            "建议检查因子在极端市场环境（如2015年股灾、2020年疫情冲击）下的表现，评估尾部风险",
            "建议对因子进行极端行情压力测试，验证在历史最大回撤期间因子是否仍能提供有效信号",
        ])

    if not has_cap:
        suggestions_pool.extend([
            "建议按市值分组回测，检查因子在大盘、中盘、小盘股中的表现差异，避免市值偏差",
            "建议分析因子在不同市值分组下的IC和分组收益，验证因子在不同规模股票中的有效性",
        ])

    if not has_long_horizon:
        suggestions_pool.extend([
            "建议测试因子在更长回看窗口（如60日、120日）下的表现，寻找最优参数组合",
            "建议进行参数敏感性分析，系统测试不同窗口参数下因子的表现稳定性",
        ])

    if not has_turnover:
        suggestions_pool.extend([
            "建议计算因子换手率，评估策略的交易成本和实际可执行性",
            "建议分析因子多头/空头组合的换手率，判断策略容量和交易成本对收益的侵蚀程度",
        ])

    # 基于IC表现的针对性建议
    ic_mean = evaluation_results.get("ic_mean")
    if ic_mean is not None:
        abs_ic = abs(ic_mean)
        if abs_ic < 0.02:
            suggestions_pool.extend([
                "当前IC均值偏低，建议探索因子的非线性变换（如分位数、排序标准化），可能提升预测能力",
                "建议检查因子与市场状态的交互效应，可能存在因子仅在特定市场环境下有效的条件性",
            ])
        elif abs_ic >= 0.05:
            suggestions_pool.extend([
                "因子IC表现优秀，建议进一步测试因子在不同市场板块（主板、创业板、科创板）中的表现一致性",
                "建议将因子纳入多因子组合，评估其与现有因子的相关性和边际贡献",
            ])

    ic_ir = evaluation_results.get("ic_ir")
    if ic_ir is not None and ic_ir < 0.3:
        suggestions_pool.extend([
            "IC_IR偏低表明因子稳定性不足，建议检查IC序列是否存在明显的时间趋势或结构性断点",
            "建议回测因子在不同年份的独立表现，识别因子失效的特定时间段并分析原因",
        ])

    # 通用建议
    generic_suggestions = [
        "建议将因子纳入多因子打分体系，评估其与现有因子的相关性和增量贡献",
        "建议对因子进行样本外测试，使用最近一年的数据验证因子在最新市场环境下的表现",
        "建议构建因子分组多空组合，计算纯因子收益，更准确地评估因子alpha",
        "建议分析因子收益的月度/季度分布特征，识别因子表现最佳的日历时间段",
        "建议对因子进行蒙特卡洛模拟，评估因子收益的统计显著性和数据窥探风险",
        "建议对比因子在A股、港股、美股等不同市场中的表现，评估因子的普适性",
        "建议使用Bootstrap方法对IC序列进行重抽样，计算IC均值的置信区间",
    ]
    suggestions_pool.extend(generic_suggestions)

    # 去重并选择
    unique_suggestions = list(set(suggestions_pool))
    random.shuffle(unique_suggestions)

    # 返回 2-3 条建议
    num = min(3, len(unique_suggestions))
    selected = unique_suggestions[:num]

    if num == 1:
        return selected[0]

    lines = ["基于当前评估结果，建议进行以下后续测试：", ""]
    for i, s in enumerate(selected, 1):
        lines.append(f"{i}. {s}")

    return "\n".join(lines)


# ============================================================
# 4. fallback_analysis
# ============================================================

def fallback_analysis(factor_spec: FactorSpec) -> dict:
    """完全模板化的分析结果，当 AI 不可用时使用。

    Parameters
    ----------
    factor_spec : FactorSpec
        因子规格对象

    Returns
    -------
    dict
        包含基本分析的结构化数据
    """
    category = factor_spec.category
    direction = factor_spec.expected_direction
    window = factor_spec.params.get("window", 20) if factor_spec.params else 20

    # 类别分析
    category_analysis = _get_category_analysis(category, direction)

    # 配置建议
    config_suggestions = _get_config_suggestions(category, window)

    # 风险评分
    risk_assessment = _get_risk_assessment(category)

    return {
        "factor_id": factor_spec.factor_id,
        "name_cn": factor_spec.name_cn,
        "category": category,
        "expected_direction": direction,
        "analysis_mode": "fallback_template",
        "summary": category_analysis["summary"],
        "strength": category_analysis["strength"],
        "weakness": category_analysis["weakness"],
        "best_market_condition": category_analysis["best_market"],
        "worst_market_condition": category_analysis["worst_market"],
        "config_suggestions": config_suggestions,
        "risk_assessment": risk_assessment,
        "recommended_companion_factors": _get_companion_factors(category),
        "expected_ic_range": category_analysis["expected_ic"],
        "expected_icir_range": category_analysis["expected_icir"],
        "turnover_estimate": category_analysis["turnover"],
        "research_references": category_analysis["references"],
    }


def _get_category_analysis(category: str, direction: str) -> dict:
    """获取各类别的分析模板"""
    templates = {
        "动量": {
            "summary": "动量因子是量化投资中最经典的因子之一，基于过去收益率预测未来收益。在A股市场中，动量效应整体弱于美股，"
                       "但短期反转效应（1-5日）和中期动量效应（20-60日）仍有一定预测能力。",
            "strength": "在趋势市中表现优异，信号直观易懂，alpha来源清晰",
            "weakness": "动量崩溃风险显著，市场急转时可能遭受大幅回撤；A股动量效应整体偏弱",
            "best_market": "单边上涨/下跌趋势市",
            "worst_market": "震荡市、市场急转",
            "expected_ic": "0.01 ~ 0.04",
            "expected_icir": "0.2 ~ 0.5",
            "turnover": "高（周度换手率 30%~60%）",
            "references": [
                "Jegadeesh & Titman (1993), Returns to Buying Winners and Selling Losers",
                "Asness, Moskowitz & Pedersen (2013), Value and Momentum Everywhere",
                "Liu, Stambaugh & Yuan (2019), Size and Value in China",
            ],
        },
        "反转": {
            "summary": "反转因子基于均值回归理论，认为短期过度上涨的股票将回调，超跌的股票将反弹。"
                       "A股市场短期反转效应显著，1-5日反转因子在历史回测中表现突出。",
            "strength": "在A股中短期反转效应显著，超额收益来源稳定",
            "weakness": "在强趋势市场中可能持续亏损，需要严格的风控配合",
            "best_market": "震荡市、波动率适中的市场环境",
            "worst_market": "强单边趋势市",
            "expected_ic": "-0.03 ~ -0.06",
            "expected_icir": "0.3 ~ 0.6",
            "turnover": "极高（周度换手率 50%~80%）",
            "references": [
                "De Bondt & Thaler (1985), Does the Stock Market Overreact?",
                "Lehmann (1990), Fads, Martingales, and Market Efficiency",
                "潘莉 & 徐建国 (2011), A股个股回报率的惯性与反转",
            ],
        },
        "趋势": {
            "summary": "趋势因子通过价格突破、均线交叉等方式捕捉趋势信号。在A股中，趋势因子在指数层面效果较好，"
                       "个股层面需要结合量价配合以提高信号可靠性。",
            "strength": "在趋势明确时信号可靠性高，与动量因子互补",
            "weakness": "滞后性明显，入场时机可能偏晚；震荡市假信号多",
            "best_market": "趋势明确的市场环境",
            "worst_market": "横盘整理、窄幅震荡",
            "expected_ic": "0.01 ~ 0.03",
            "expected_icir": "0.15 ~ 0.35",
            "turnover": "中（周度换手率 15%~30%）",
            "references": [
                "Moskowitz, Ooi & Pedersen (2012), Time Series Momentum",
                "Han, Zhou & Zhu (2016), A Trend Factor",
            ],
        },
        "波动率": {
            "summary": "波动率因子基于低波动率异常现象，即低波动股票的风险调整后收益反而优于高波动股票。"
                       "该效应在全球多个市场得到验证，A股中同样存在。",
            "strength": "防御性突出，在市场下跌时表现优异，风险调整后收益稳健",
            "weakness": "牛市环境中弹性不足，可能跑输高贝塔组合",
            "best_market": "下跌市、波动率上升阶段",
            "worst_market": "普涨牛市",
            "expected_ic": "-0.02 ~ -0.05",
            "expected_icir": "0.25 ~ 0.55",
            "turnover": "低（月度换手率 20%~40%）",
            "references": [
                "Ang, Hodrick, Xing & Zhang (2006), The Cross-Section of Volatility",
                "Frazzini & Pedersen (2014), Betting Against Beta",
            ],
        },
        "成交量": {
            "summary": "成交量因子捕捉量价关系中的alpha信号，包括放量上涨、缩量下跌等经典技术形态。"
                       "在A股市场中，成交量因子与价格动量因子结合使用效果更佳。",
            "strength": "量价结合可以提高信号可靠性，识别主力资金动向",
            "weakness": "小盘股中成交量容易被操纵，信号噪声较大",
            "best_market": "资金活跃、成交量放大的市场",
            "worst_market": "缩量阴跌、流动性枯竭",
            "expected_ic": "0.01 ~ 0.03",
            "expected_icir": "0.15 ~ 0.35",
            "turnover": "中高（周度换手率 25%~50%）",
            "references": [
                "Gervais, Kaniel & Mingelgrin (2001), The High-Volume Return Premium",
                "Lee & Swaminathan (2000), Price Momentum and Trading Volume",
            ],
        },
        "价值": {
            "summary": "价值因子基于买入低估股票、卖出高估股票的投资理念。在A股中，价值因子长期有效，"
                       "但近年来受成长风格主导，表现有所波动。",
            "strength": "理论基础扎实，长期有效性经过多市场验证，防御性较好",
            "weakness": "价值陷阱风险，低估值可能反映基本面恶化；成长风格主导时可能长期跑输",
            "best_market": "价值风格占优、利率上行阶段",
            "worst_market": "成长风格主导、流动性充裕环境",
            "expected_ic": "0.01 ~ 0.04",
            "expected_icir": "0.2 ~ 0.5",
            "turnover": "低（月度换手率 15%~30%）",
            "references": [
                "Fama & French (1992), The Cross-Section of Expected Stock Returns",
                "Fama & French (2015), A Five-Factor Asset Pricing Model",
            ],
        },
        "质量": {
            "summary": "质量因子基于公司财务质量指标，如ROE、毛利率、资产负债率等。"
                       "高质量公司在长期来看具有更高的可持续竞争优势和更低的尾部风险。",
            "strength": "长期有效性稳定，熊市防御性突出，与价值因子互补",
            "weakness": "财务数据更新频率低，信号滞后；财务造假风险",
            "best_market": "风险偏好下降、市场调整阶段",
            "worst_market": "高风险偏好、题材炒作阶段",
            "expected_ic": "0.02 ~ 0.05",
            "expected_icir": "0.3 ~ 0.6",
            "turnover": "极低（季度/半年度换仓）",
            "references": [
                "Asness, Frazzini & Pedersen (2019), Quality Minus Junk",
                "Novy-Marx (2013), The Other Side of Value: The Gross Profitability Premium",
            ],
        },
        "规模": {
            "summary": "规模因子（小盘股效应）认为小市值公司长期来看具有更高的预期收益。"
                       "在A股中，小盘股效应历史上显著，但近年来随着注册制推进和市场结构变化，效果有所减弱。",
            "strength": "在流动性宽松、风险偏好高时弹性强",
            "weakness": "小盘股流动性风险、壳价值退潮、注册制下小盘股供给增加",
            "best_market": "流动性宽松、市场风险偏好高",
            "worst_market": "流动性收紧、避险情绪升温",
            "expected_ic": "-0.02 ~ -0.05",
            "expected_icir": "0.2 ~ 0.5",
            "turnover": "中低（月度换手率 20%~40%）",
            "references": [
                "Banz (1981), The Relationship Between Return and Market Value",
                "Fama & French (1993), Common Risk Factors in the Returns on Stocks and Bonds",
            ],
        },
        "情绪": {
            "summary": "情绪因子通过新闻舆情、分析师评级、社交媒体等数据捕捉市场情绪变化。"
                       "在A股散户占比较高的市场结构中，情绪因子具有一定预测能力。",
            "strength": "在信息快速传播的市场中反应灵敏，捕捉短期交易机会",
            "weakness": "信号噪声大，需要高频数据支持；情绪可能已经是价格的滞后反映",
            "best_market": "信息密集发布期、财报季",
            "worst_market": "信息真空期、市场平淡期",
            "expected_ic": "0.01 ~ 0.03",
            "expected_icir": "0.15 ~ 0.35",
            "turnover": "高（周度换手率 30%~60%）",
            "references": [
                "Baker & Wurgler (2006), Investor Sentiment and the Cross-Section",
                "Tetlock (2007), Giving Content to Investor Sentiment",
            ],
        },
        "成长": {
            "summary": "成长因子基于公司盈利增长、营收增长等指标。在流动性充裕、风险偏好高的环境中，"
                       "成长因子表现优异，但加息周期中可能承压。",
            "strength": "高增长公司在牛市中弹性强，alpha来源清晰",
            "weakness": "估值敏感，加息周期承压；增长不及预期风险",
            "best_market": "流动性充裕、风险偏好高",
            "worst_market": "加息周期、风险偏好下降",
            "expected_ic": "0.01 ~ 0.04",
            "expected_icir": "0.2 ~ 0.45",
            "turnover": "中低（季度换仓）",
            "references": [
                "Fama & French (2015), A Five-Factor Asset Pricing Model",
                "Chen, Novy-Marx & Zhang (2010), An Alternative Three-Factor Model",
            ],
        },
        "流动性": {
            "summary": "流动性因子捕捉股票流动性特征对收益的影响。低流动性股票通常存在流动性溢价，"
                       "但需注意策略容量和极端行情下的流动性风险。",
            "strength": "流动性溢价在各市场普遍存在，理论基础扎实",
            "weakness": "策略容量极其有限，规模扩大后收益快速衰减；流动性危机时风险剧增",
            "best_market": "正常市场环境",
            "worst_market": "流动性危机、市场恐慌",
            "expected_ic": "-0.01 ~ -0.04",
            "expected_icir": "0.15 ~ 0.4",
            "turnover": "低（月度换手率 15%~30%）",
            "references": [
                "Amihud & Mendelson (1986), Asset Pricing and the Bid-Ask Spread",
                "Pastor & Stambaugh (2003), Liquidity Risk and Expected Stock Returns",
            ],
        },
    }

    default_template = {
        "summary": "该因子属于自定义因子类别，建议进行充分的回测验证后再投入使用。",
        "strength": "待验证",
        "weakness": "待验证",
        "best_market": "待验证",
        "worst_market": "待验证",
        "expected_ic": "待测试",
        "expected_icir": "待测试",
        "turnover": "待估算",
        "references": [],
    }

    return templates.get(category, default_template)


def _get_config_suggestions(category: str, window: int) -> list[str]:
    """获取配置建议"""
    suggestions = [
        f"建议使用 {window} 日窗口进行初始测试，同时测试 {window // 2} 日和 {window * 2} 日窗口的敏感性",
        "建议使用 MAD 3倍标准差或分位数方法进行极端值处理",
    ]

    if category in ("动量", "反转", "趋势"):
        suggestions.append("建议使用行业中性化处理，排除行业暴露影响")
    if category in ("成交量", "流动性"):
        suggestions.append("建议剔除涨跌停和长期停牌股票，避免流动性偏差")
    if category in ("波动率",):
        suggestions.append("建议使用稳健的波动率估计方法，降低极端值影响")
    if category in ("价值", "质量", "成长"):
        suggestions.append("建议对财务数据进行滞后处理，避免前视偏差")

    return suggestions


def _get_risk_assessment(category: str) -> dict:
    """获取风险评估"""
    risk_profiles = {
        "动量": {"level": "中高", "score": 6.5, "main_risk": "动量崩溃风险"},
        "反转": {"level": "高", "score": 7.0, "main_risk": "趋势延续风险"},
        "趋势": {"level": "中", "score": 5.5, "main_risk": "假突破风险"},
        "波动率": {"level": "中低", "score": 4.5, "main_risk": "尾部风险"},
        "成交量": {"level": "中", "score": 5.0, "main_risk": "流动性陷阱"},
        "价值": {"level": "中低", "score": 4.0, "main_risk": "价值陷阱"},
        "质量": {"level": "低", "score": 3.5, "main_risk": "财务数据滞后"},
        "规模": {"level": "中", "score": 5.5, "main_risk": "壳价值退潮"},
        "情绪": {"level": "高", "score": 7.5, "main_risk": "噪声过大"},
        "成长": {"level": "中", "score": 5.0, "main_risk": "增长不及预期"},
        "流动性": {"level": "中高", "score": 6.0, "main_risk": "流动性危机"},
    }
    default = {"level": "中", "score": 5.0, "main_risk": "待评估"}
    return risk_profiles.get(category, default)


def _get_companion_factors(category: str) -> list[str]:
    """获取推荐的搭配因子"""
    companion_map = {
        "动量": ["反转因子（对冲动量崩溃）", "波动率因子（控制尾部风险）"],
        "反转": ["动量因子（识别趋势强度）", "成交量因子（确认信号）"],
        "趋势": ["波动率因子（过滤假突破）", "成交量因子（量价配合）"],
        "波动率": ["动量因子（增强收益弹性）", "质量因子（降低尾部风险）"],
        "成交量": ["动量因子（量价结合）", "趋势因子（确认方向）"],
        "价值": ["质量因子（排除价值陷阱）", "动量因子（避免左侧过早入场）"],
        "质量": ["价值因子（避免估值过高）", "规模因子（控制市值偏差）"],
        "规模": ["流动性因子（控制流动性风险）", "波动率因子（控制小盘波动）"],
        "情绪": ["反转因子（情绪极端后的回归）", "成交量因子（验证情绪信号）"],
        "成长": ["质量因子（验证增长质量）", "价值因子（控制估值风险）"],
        "流动性": ["规模因子（流动性溢价主要存在于小盘）", "波动率因子（风险控制）"],
    }
    return companion_map.get(category, ["动量因子", "价值因子"])


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "parse_text_to_spec",
    "generate_evidence_summary",
    "generate_next_test_suggestion",
    "fallback_analysis",
    "generate_summary",
]


def generate_summary(results: dict) -> str:
    """生成 AI 解释摘要（`09_鉴证运行.py` 使用的兼容接口）"""
    trad = results.get("traditional_eval", {})
    evals = {
        "ic_mean": trad.get("ic_mean"),
        "rank_ic_mean": trad.get("rank_ic_mean"),
        "icir": trad.get("icir"),
        "coverage": trad.get("coverage"),
    }

    stress = results.get("stress_test", {})
    if isinstance(stress, dict):
        test_results = stress.get("test_results", [])
        if isinstance(test_results, list):
            evals["stress_passed"] = sum(1 for s in test_results if s.get("verdict") == "pass")
            evals["stress_total"] = len(test_results)

    dup = results.get("duplicate_check", {})
    if isinstance(dup, dict):
        evals["overall_verdict"] = "不相似" if dup.get("duplicates_found", 0) == 0 else "中等相似"

    # 构建一个简单的因子 spec 用于模板化总结
    from models.factor_spec import FactorSpec
    dummy_spec = FactorSpec(
        factor_id=results.get("input_check", {}).get("factor_id", "unknown"),
        name="custom",
        name_cn=results.get("input_check", {}).get("factor_name", "未命名因子"),
        category="其他",
        expected_direction="higher",
    )

    return generate_evidence_summary(
        factor_spec=dummy_spec,
        evaluation_results=evals,
    )