import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import io
import platform

# ==============================================================================
# 🚀 界面定制 (全量保留)
# ==============================================================================
hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            .viewerBadge_container__1QSob {display: none;}
            #stDecoration {display:none;}
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

# ==============================================================================
# 1. 🎨 页面设置
# ==============================================================================
st.set_page_config(page_title="多品种套保稳定性回测系统", layout="wide", page_icon="🛡️")
plt.style.use('seaborn-v0_8-whitegrid')

@st.cache_resource
def set_font():
    sys_name = platform.system()
    if sys_name == "Windows": plt.rcParams['font.sans-serif'] = ['SimHei']
    elif sys_name == "Darwin": plt.rcParams['font.sans-serif'] = ['Arial Unicode MS']
    else: plt.rcParams['font.sans-serif'] = ['WenQuanYi Micro Hei']
    plt.rcParams['axes.unicode_minus'] = False
set_font()

# ==============================================================================
# 2. 🎛️ 侧边栏：加入品种自变量
# ==============================================================================
st.sidebar.header("🛠️ 策略自变量配置")
uploaded_file = st.sidebar.file_uploader("上传数据文件 (CSV)", type=['csv'])

with st.sidebar.expander("📝 品种合约参数", expanded=True):
    # 新增：合约乘数自变量
    multiplier = st.number_input("合约乘数 (一手的数量)", value=10, min_value=1, help="例如：螺纹钢10, 铜5, 黄金1000")
    lots = st.number_input("交易手数", value=3, min_value=1)
    # 自动计算总吨数/数量
    total_quantity = lots * multiplier
    st.info(f"当前对冲总规模: {total_quantity} 单位")

with st.sidebar.expander("⚙️ 风控参数", expanded=True):
    hedge_ratio = st.slider("套保比例", 0.0, 1.2, 1.0, 0.1)
    margin_rate = st.number_input("保证金率 (如0.12)", value=0.12, format="%.2f")
    inject_ratio = st.number_input("补金警戒线 (倍)", value=1.2)
    withdraw_ratio = st.number_input("提盈触发线 (倍)", value=1.5)
    holding_days = st.sidebar.slider("模拟持仓周期 (天)", 7, 90, 30)

# ==============================================================================
# 3. 🧠 核心计算逻辑 (加入乘数变量)
# ==============================================================================
@st.cache_data
def process_data(df_input, q, ratio, m_rate, inject_r, withdraw_r, days):
    df = df_input.copy().reset_index(drop=True)
    
    # 核心公式更新：盈亏 = 价格变动 * 总量 (手数 * 乘数)
    df['Basis'] = df['Spot'] - df['Futures']
    df['Cycle_PnL_NoHedge'] = df['Spot'].diff(days) * q
    df['Cycle_Futures_PnL'] = -(df['Futures'].diff(days)) * q * ratio
    df['Cycle_PnL_Hedge'] = df['Cycle_PnL_NoHedge'] + df['Cycle_Futures_PnL']

    equity_list, cash_in_list, cash_out_list, margin_req_list = [], [], [], []
    
    # 初始权益计算
    current_price = df['Futures'].iloc[0]
    initial_equity = current_price * q * ratio * m_rate * inject_r
    current_equity = initial_equity

    for i in range(len(df)):
        price = df['Futures'].iloc[i]
        if i > 0:
            # 每日盈亏更新
            current_equity += -(price - df['Futures'].iloc[i - 1]) * q * ratio

        # 实时所需保证金
        req_margin = price * q * ratio * m_rate
        margin_req_list.append(req_margin)

        # 补金与提金逻辑
        in_amt, out_amt = 0, 0
        if current_equity < req_margin * inject_r:
            in_amt = (req_margin * inject_r) - current_equity
            current_equity += in_amt
        elif current_equity > req_margin * withdraw_r:
            out_amt = current_equity - (req_margin * withdraw_r)
            current_equity -= out_amt

        cash_in_list.append(in_amt)
        cash_out_list.append(out_amt)
        equity_list.append(current_equity)

    df['Account_Equity'] = equity_list
    df['Margin_Required'] = margin_req_list
    df['Cash_Injection'] = cash_in_list
    df['Cash_Withdrawal'] = cash_out_list
    df['Line_Inject'] = df['Margin_Required'] * inject_r
    df['Line_Withdraw'] = df['Margin_Required'] * withdraw_r

    # 综合价值变动
    cum_net_cash = pd.Series(cash_out_list).cumsum() - pd.Series(cash_in_list).cumsum()
    df['Value_Change_NoHedge'] = (df['Spot'] - df['Spot'].iloc[0]) * q
    df['Value_Change_Hedged'] = (df['Spot'] * q) + df['Account_Equity'] + cum_net_cash - ((df['Spot'].iloc[0] * q) + initial_equity)
    
    return df

# ==============================================================================
# 4. 📊 主界面
# ==============================================================================
st.title("🛡️ 多品种套保稳定性回测系统")
st.caption(f"当前品种配置：{multiplier} 单位/手 | 目标规模：{total_quantity} 单位")

if uploaded_file:
    try:
        raw_df = pd.read_csv(uploaded_file, encoding='gbk')
    except:
        raw_df = pd.read_csv(uploaded_file, encoding='utf-8-sig')
    
    raw_df.columns = [str(c).strip() for c in raw_df.columns]
    col_time = next((c for c in raw_df.columns if '时间' in c or 'Date' in c), None)
    col_spot = next((c for c in raw_df.columns if '现货' in c), None)
    col_fut = next((c for c in raw_df.columns if '期货' in c and '价格' in c), None)

    if col_time and col_spot and col_fut:
        raw_df[col_time] = pd.to_datetime(raw_df[col_time])
        df_clean = raw_df.rename(columns={col_time:'Date', col_spot:'Spot', col_fut:'Futures'}).sort_values('Date')
        
        # 调用计算逻辑
        df = process_data(df_clean, total_quantity, hedge_ratio, margin_rate, inject_ratio, withdraw_ratio, holding_days)

        # --- 数据看板 ---
        std_raw = df['Value_Change_NoHedge'].std() / 10000
        std_hedge = df['Value_Change_Hedged'].std() / 10000
        stability_boost = (1 - std_hedge / std_raw) * 100 if std_raw != 0 else 0
        loss_saved = (df['Value_Change_Hedged'].min() - df['Value_Change_NoHedge'].min()) / 10000

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("单手规模", f"{multiplier} 单位")
        c2.metric("对冲稳定性提升", f"{stability_boost:.1f}%", delta=f"剩余波动:{std_hedge:.1f}万")
        c3.metric("累计调仓次数", f"{len(df[df['Cash_Injection']>0]) + len(df[df['Cash_Withdrawal']>0])} 次")
        c4.metric("最大风险挽回", f"{loss_saved:.2f} 万")

        # --- 图表展示 (按要求排序) ---
        t1, t2, t3, t4 = st.tabs(["📉 价格基差监控", "🛡️ 对冲波动稳定性", "📊 风险概率分布", "🏦 资金通道监管"])

        with t1:
            fig1, ax1 = plt.subplots(figsize=(10, 4))
            ax1.plot(df['Date'], df['Spot']/10000, label='现货价格')
            ax1.plot(df['Date'], df['Futures']/10000, ls='--', label='期货价格')
            ax1_r = ax1.twinx()
            ax1_r.fill_between(df['Date'], df['Basis']/10000, 0, color='gray', alpha=0.1, label='基差')
            ax1.legend(loc='upper left'); st.pyplot(fig1)

        with t2:
            fig2, ax2 = plt.subplots(figsize=(10, 4))
            ax2.plot(df['Date'], df['Value_Change_NoHedge']/10000, color='red', alpha=0.3, label='未套保波动')
            ax2.plot(df['Date'], df['Value_Change_Hedged']/10000, color='green', lw=2, label='套保后净值')
            ax2.axhline(0, color='black', ls=':', alpha=0.3); ax2.legend(); st.pyplot(fig2)

        with t3:
            fig3, ax3 = plt.subplots(figsize=(10, 4))
            sns.kdeplot(df['Cycle_PnL_NoHedge'].dropna()/10000, fill=True, color='red', alpha=0.3, label='未套保分布')
            sns.kdeplot(df['Cycle_PnL_Hedge'].dropna()/10000, fill=True, color='green', alpha=0.5, label='套保后分布')
            ax3.set_xlabel("周期盈亏 (万元)"); ax3.legend(); st.pyplot(fig3)

        with t4:
            fig4, ax4 = plt.subplots(figsize=(10, 4))
            ax4.plot(df['Date'], df['Account_Equity']/10000, color='black', alpha=0.6, label='期货账户权益')
            ax4.fill_between(df['Date'], df['Line_Inject']/10000, df['Line_Withdraw']/10000, color='gray', alpha=0.1)
            # 标注调仓点
            inj = df[df['Cash_Injection']>0]
            wit = df[df['Cash_Withdrawal']>0]
            ax4.scatter(inj['Date'], inj['Account_Equity']/10000, color='red', marker='^', s=50, label='补仓')
            ax4.scatter(wit['Date'], wit['Account_Equity']/10000, color='blue', marker='v', s=50, label='出金')
            ax4.legend(loc='upper left', ncol=2); st.pyplot(fig4)

        # --- 自动生成结论 ---
        st.markdown("---")
        st.subheader("📝 策略稳定性简报")
        st.write(f"1. **规模适配**：针对该品种（{multiplier}单位/手），本次模拟共回测了 **{lots}** 手的对冲规模。")
        st.write(f"2. **稳定性分析**：对冲后资产波动标准差从 **{std_raw:.2f}万** 缩减至 **{std_hedge:.2f}万**。")
        st.write(f"3. **资金调度**：在当前警戒线下，共触发补仓 **{len(inj)}** 次。")

        # 下载
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine='openpyxl') as w: df.to_excel(w, index=False)
        st.download_button("📥 下载完整回测数据", data=buf.getvalue(), file_name='回测数据.xlsx')
else:
    st.info("💡 请在左侧上传包含‘现货’、‘期货’价格的 CSV 文件。")



