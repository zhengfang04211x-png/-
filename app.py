import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import io
import platform

# ==============================================================================
# 🚀 界面定制 (保留你原来的所有样式)
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
# 1. 🎨 页面基本设置与字体 (保留你原来的适配逻辑)
# ==============================================================================
st.set_page_config(page_title="企业套保资金风控系统", layout="wide", page_icon="📈")
plt.style.use('seaborn-v0_8-whitegrid')

system_name = platform.system()
if system_name == "Windows":
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial']
elif system_name == "Darwin":
    plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'PingFang SC']
else:
    plt.rcParams['font.sans-serif'] = ['WenQuanYi Micro Hei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# ==============================================================================
# 2. 🎛️ 侧边栏：加入“合约乘数”自变量
# ==============================================================================
st.sidebar.header("🛠️ 参数配置面板")
uploaded_file = st.sidebar.file_uploader("上传数据文件 (CSV)", type=['csv'])

st.sidebar.subheader("🏭 业务场景")
# --- 新增自变量：合约乘数 ---
multiplier = st.sidebar.number_input("合约乘数 (每手数量)", value=10, step=1, help="例如：螺纹钢10, 铜5")
lots = st.sidebar.number_input("下单手数", value=3, step=1)
# 自动通过 手数 * 乘数 得到原本代码里的 quantity
quantity = lots * multiplier 
st.sidebar.caption(f"📢 当前总持仓规模: {quantity} 单位")

hedge_ratio = st.sidebar.slider("套保比例 (1.0 = 100%)", 0.0, 1.2, 1.0, 0.1)
margin_rate = st.sidebar.number_input("保证金率", value=0.12, step=0.01, format="%.2f")

st.sidebar.subheader("💰 资金区间管理")
inject_ratio = st.sidebar.number_input("补金警戒线 (倍数)", value=1.2, step=0.05)
withdraw_ratio = st.sidebar.number_input("提盈触发线 (倍数)", value=1.5, step=0.05)

st.sidebar.subheader("⏳ 模拟设置")
holding_days = st.sidebar.slider("库存周转/持仓周期 (天)", 7, 90, 30)

# ==============================================================================
# 3. 🧠 核心计算逻辑 (完全保留你原始的 process_data 逻辑)
# ==============================================================================
@st.cache_data
def process_data(df_input, q, ratio, m_rate, inject_r, withdraw_r, days):
    df = df_input.copy().reset_index(drop=True)

    # 基础指标计算
    df['Basis'] = df['Spot'] - df['Futures']
    df['Cycle_PnL_NoHedge'] = df['Spot'].diff(days) * q
    df['Cycle_Futures_PnL'] = -(df['Futures'].diff(days)) * q * ratio
    df['Cycle_PnL_Hedge'] = df['Cycle_PnL_NoHedge'] + df['Cycle_Futures_PnL']

    # 资金流模拟
    equity_list, margin_req_list = [], []
    cash_in_list, cash_out_list = [], []
    risk_degree_list = []

    current_price = df['Futures'].iloc[0]
    initial_equity = current_price * q * ratio * m_rate * inject_r
    current_equity = initial_equity

    for i in range(len(df)):
        price = df['Futures'].iloc[i]
        if i > 0:
            daily_pnl = -(price - df['Futures'].iloc[i - 1]) * q * ratio
            current_equity += daily_pnl

        req_margin = price * q * ratio * m_rate
        margin_req_list.append(req_margin)

        thresh_low = req_margin * inject_r
        thresh_high = req_margin * withdraw_r

        in_amt, out_amt = 0, 0
        if current_equity < thresh_low:
            in_amt = thresh_low - current_equity
            current_equity += in_amt
        elif current_equity > thresh_high:
            out_amt = current_equity - thresh_high
            current_equity -= out_amt

        cash_in_list.append(in_amt)
        cash_out_list.append(out_amt)
        equity_list.append(current_equity)
        risk_degree_list.append((current_equity / req_margin) if req_margin > 0 else 0)

    df['Account_Equity'] = equity_list
    df['Margin_Required'] = margin_req_list
    df['Cash_Injection'] = cash_in_list
    df['Cash_Withdrawal'] = cash_out_list
    df['Risk_Degree'] = risk_degree_list
    df['Line_Inject'] = df['Margin_Required'] * inject_r
    df['Line_Withdraw'] = df['Margin_Required'] * withdraw_r

    # 净值计算
    cum_net_cash = pd.Series(cash_out_list).cumsum() - pd.Series(cash_in_list).cumsum()
    base_asset = (df['Spot'].iloc[0] * q) + initial_equity
    curr_asset = (df['Spot'] * q) + df['Account_Equity'] + cum_net_cash

    df['Value_Change_NoHedge'] = (df['Spot'] - df['Spot'].iloc[0]) * q
    df['Value_Change_Hedged'] = curr_asset - base_asset

    return df

# ==============================================================================
# 4. 📊 主界面展示逻辑 (完全还原你原本的 Tab 分页和展示)
# ==============================================================================
st.title("📊 企业套期保值资金风控看板")
st.markdown("---")

if uploaded_file is not None:
    try:
        raw_df = pd.read_csv(uploaded_file, encoding='gbk')
    except:
        raw_df = pd.read_csv(uploaded_file, encoding='utf-8-sig')
    
    raw_df.columns = [str(c).strip() for c in raw_df.columns]
    col_time = next((c for c in raw_df.columns if '时间' in c or 'Date' in c), None)
    col_spot = next((c for c in raw_df.columns if '现货' in c), None)
    col_fut = next((c for c in raw_df.columns if ('期货' in c or '主力' in c) and '价格' in c), None)

    if not (col_time and col_spot and col_fut):
        st.error("无法识别列名，请确保包含：时间, 现货, 期货价格")
    else:
        raw_df = raw_df.rename(columns={col_time: 'Date', col_spot: 'Spot', col_fut: 'Futures'})
        raw_df['Date'] = pd.to_datetime(raw_df['Date'])
        for col in ['Spot', 'Futures']:
            raw_df[col] = pd.to_numeric(raw_df[col].astype(str).str.replace(',', ''), errors='coerce')
        raw_df = raw_df.sort_values('Date').reset_index(drop=True)

        st.sidebar.subheader("📅 样本区间选择")
        min_date, max_date = raw_df['Date'].min().to_pydatetime(), raw_df['Date'].max().to_pydatetime()
        date_range = st.sidebar.date_input("分析时间", value=(min_date, max_date))

        if isinstance(date_range, tuple) and len(date_range) == 2:
            mask = (raw_df['Date'].dt.date >= date_range[0]) & (raw_df['Date'].dt.date <= date_range[1])
            df = process_data(raw_df.loc[mask], quantity, hedge_ratio, margin_rate, inject_ratio, withdraw_ratio, holding_days)

            # --- 顶部 Metrics ---
            c1, c2, c3, c4 = st.columns(4)
            t_inject = df['Cash_Injection'].sum() / 10000
            t_withdraw = df['Cash_Withdrawal'].sum() / 10000
            c1.metric("累计补入资金", f"{t_inject:.2f} 万")
            c2.metric("累计提取盈余", f"{t_withdraw:.2f} 万")
            c3.metric("资金净回流", f"{(t_withdraw - t_inject):.2f} 万")
            c4.metric("最新风险度", f"{df['Risk_Degree'].iloc[-1] * 100:.1f}%")

            # --- 还原你原始的四个 Tab ---
            tab1, tab2, tab3, tab4 = st.tabs(["📉 价格与基差", "🏦 资金通道监控", "🛡️ 对冲效果对比", "📊 风险分布"])

            with tab1:
                fig1, ax1 = plt.subplots(figsize=(10, 5))
                ax1.plot(df['Date'], df['Spot'] / 10000, 'b-', label='现货')
                ax1.plot(df['Date'], df['Futures'] / 10000, 'orange', linestyle='--', label='期货')
                ax1_r = ax1.twinx()
                ax1_r.fill_between(df['Date'], df['Basis']/10000, 0, color='gray', alpha=0.2)
                ax1.legend(loc='upper left'); st.pyplot(fig1)

            with tab2:
                fig3, ax3 = plt.subplots(figsize=(10, 5))
                ax3.fill_between(df['Date'], df['Line_Inject']/10000, df['Line_Withdraw']/10000, color='gray', alpha=0.1)
                ax3.plot(df['Date'], df['Account_Equity']/10000, color='green', linewidth=2, label='权益')
                ax3.plot(df['Date'], df['Line_Inject']/10000, 'r--', alpha=0.5, label='补金线')
                ax3.plot(df['Date'], df['Line_Withdraw']/10000, 'b--', alpha=0.5, label='提金线')
                ax3.legend(loc='upper left'); st.pyplot(fig3)

            with tab3:
                fig4, ax4 = plt.subplots(figsize=(10, 5))
                v_raw, v_hedge = df['Value_Change_NoHedge']/10000, df['Value_Change_Hedged']/10000
                ax4.plot(df['Date'], v_raw, 'r-', alpha=0.3, label='未套保')
                ax4.plot(df['Date'], v_hedge, 'g-', linewidth=2, label='套保后')
                ax4.axhline(0, color='black', linestyle=':', alpha=0.3)
                ax4.legend(); st.pyplot(fig4)
                reduce = (1 - v_hedge.std() / v_raw.std()) * 100 if v_raw.std() != 0 else 0
                st.caption(f"📊 统计结论: 套保策略将资产波动率降低了 **{reduce:.1f}%**。")

            with tab4:
                fig2, ax2 = plt.subplots(figsize=(10, 5))
                sns.kdeplot(df['Cycle_PnL_NoHedge'].dropna()/10000, fill=True, color='red', alpha=0.3, label='未套保', ax=ax2)
                sns.kdeplot(df['Cycle_PnL_Hedge'].dropna()/10000, fill=True, color='green', alpha=0.5, label='套保后', ax=ax2)
                ax2.legend(); st.pyplot(fig2)

            # --- 下载功能 ---
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False)
            st.download_button("📥 下载 Excel 分析日报", data=output.getvalue(), file_name='回测报告.xlsx')
else:
    st.info("👆 请在左侧上传 CSV 数据文件。")




