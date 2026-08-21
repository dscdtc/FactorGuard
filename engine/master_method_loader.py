from models.master_method import MasterMethodSpec, Principle


def load_demo_master_method() -> MasterMethodSpec:
    return MasterMethodSpec(
        method_id="berkshire-quality",
        name="巴菲特质量框架（去劣筛选）",
        source_title="AI Berkshire Quality Screen",
        source_reference="DataSource/ai-berkshire/codex-skills/quality-screen/",
        source_excerpt="通过7条去劣指标和3条豁免规则，系统化筛选高质量企业",
        principles=[
            Principle(
                id=1, name="资本效率",
                description="10年平均ROE不应低于8%",
                master_perspective="巴菲特",
                proxy_factors=["ROE稳定性因子"],
                proxy_grade="B",
                proxy_limitations="本地数据含净利润/净资产，可计算ROE。但需10年连续数据，早期数据缺失。",
                measurable=True
            ),
            Principle(
                id=2, name="真金白银",
                description="5年累计自由现金流应为正",
                master_perspective="巴菲特",
                proxy_factors=["经营现金流/净利润比"],
                proxy_grade="C",
                proxy_limitations="需现金流量表数据，本地数据缺失，需akshare补充。",
                measurable=True
            ),
            Principle(
                id=3, name="偿债安全",
                description="利息覆盖倍数不应低于2倍",
                master_perspective="巴菲特",
                proxy_factors=["EBIT/利息支出"],
                proxy_grade="C",
                proxy_limitations="需利润表+附注数据，本地数据缺失。",
                measurable=False
            ),
            Principle(
                id=4, name="定价权",
                description="长期毛利率不应低于15%",
                master_perspective="段永平",
                proxy_factors=["毛利率稳定性因子"],
                proxy_grade="C",
                proxy_limitations="需收入和成本明细数据，本地数据缺失。",
                measurable=True
            ),
            Principle(
                id=5, name="利润质量",
                description="经营现金流/净利润不应低于0.7",
                master_perspective="李录",
                proxy_factors=["现金流质量因子"],
                proxy_grade="C",
                proxy_limitations="需现金流数据，本地数据缺失。",
                measurable=False
            ),
            Principle(
                id=6, name="抗风险能力",
                description="长期净利率不应低于5%",
                master_perspective="芒格",
                proxy_factors=["净利率因子"],
                proxy_grade="B",
                proxy_limitations="本地数据含净利润，可计算。但需区分经常性损益。",
                measurable=True
            ),
            Principle(
                id=7, name="股东利益",
                description="5年总股本膨胀不应超过20%",
                master_perspective="巴菲特",
                proxy_factors=["股本变化因子"],
                proxy_grade="B",
                proxy_limitations="本地数据可推算股本变化，但需注意送转股影响。",
                measurable=True
            ),
        ],
        exemption_rules=[
            {"id": "A", "name": "IPO豁免", "description": "上市不足5年的公司豁免指标1(ROE)和指标2(FCF)的长期要求"},
            {"id": "B", "name": "行业豁免", "description": "金融行业豁免指标3(利息覆盖)，因金融企业杠杆结构不同"},
            {"id": "C", "name": "周期豁免", "description": "强周期行业豁免指标1(ROE)的10年平均要求，改为考察完整周期"},
        ],
        data_requirements=["净利润", "净资产", "总股本", "经营现金流", "利息支出", "毛利率", "净利率"],
        limitations="通过筛选不等于确定好。仍需进一步研究：管理层质量、行业竞争格局、估值合理性。",
        ai_berkshire_skill="quality-screen"
    )