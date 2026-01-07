import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import io
import platform
import matplotlib.font_manager as fm

# ==============================================================================
# 1. 🎨 页面基本设置与字体修复 (解决 GitHub 部署乱码)
# ==============================================================================
st.set_page_config(page_title="企业套保资金风控系统", layout="wide", page_icon="📈")

# 设置绘图风格
plt.style.use('seaborn-v0_8-whitegrid')

def set_matplot_zh_font():
    # 针对 Linux (GitHub/Streamlit Cloud) 优先使用文泉驿微米黑
    plt.rcParams['font.sans-serif'] = ['WenQuanYi Micro Hei', 'SimHei', 'Microsoft YaHei', 'Arial Unicode MS', 'sans-serif']
    plt.rcParams['axes.unicode_minus'] = False
    try:
        # 强制尝试加载 Linux 下的路径
        zh_font = fm.FontProperties(fname='/usr/share/fonts/truetype/wqy/wqy-microhei.ttc')
        if zh_font:
            plt.rcParams['font.family'] = zh_font.get_name()
    except:
        pass

set_matplot_zh_font()

# ==============================================================================
# 2. 🎛️ 侧边栏：参数控制中心
# ==============================================================================
st.sidebar.header("🛠️ 参数配置面板")

# A. 文件上传
uploaded_file = st.sidebar.file_uploader("上传数据文件 (CSV)", type=['csv'])

# B. 业务参数
st.sidebar.subheader("🏭 业务场景")
quantity = st.sidebar.number_input("持仓数量 (吨)", value=30, step=10)
hedge_ratio = st.sidebar.slider("套保比例 (1.0 = 100%)", 0.0, 1.2, 1.0, 0.1)
margin_rate = st.sidebar.number_input("保证金率 (0.12 = 12%)", value=0.12, step=0.01, format="%.2f")

# C. 资金策略
st.sidebar.subheader("💰 资金区间管理")
inject_ratio = st.sidebar.number_input("补金警戒线 (倍数)", value=1.2, step=0.05)
withdraw_ratio = st.sidebar.number_input("提盈触发线 (倍数)", value=1.5, step=0.05)

# D. 模拟参数
st.sidebar.subheader("⏳ 模拟设置")
holding_days = st.sidebar.slider("库存周转/持仓周期 (天)", 7, 90, 30)


# ==============================================================================
# 3. 🧠 核心计算逻辑 (分步处理)
# ==============================================================================
@st.cache_data
def load_raw_data(file):
    """初步加载数据并统一列名"""
    try:
        df = pd.read_csv(file, encoding='gbk')
    except:
        df = pd.read_csv(file, encoding='utf-8-sig')
    
    df.columns = [str(c).strip() for c in df.columns]
    cols = df.columns
    col_time = next((c for c in cols if '时间' in c or 'Date' in c), None)
    col_spot = next((c for c in cols if '现货' in c), None)
    col_fut = next((c for c in cols if ('期货' in c or '主力' in c) and '价格' in c), None)
    
    if not (col_time and col_spot and col_fut):
        return None, "无法识别列名，请确保包含：时间/Date, 现货, 期货/主力合约价格"
    
    df = df.rename(columns={col_time: 'Date', col_spot: 'Spot', col_fut: 'Futures'})
    df['Date'] = pd.to_datetime(df['Date'])
    for col in ['Spot', 'Futures']:
        df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', ''), errors='coerce')
    df = df.sort_values('Date').reset_index(drop=True)
    return df, None

def run_simulation(df, q, ratio, m_rate, inject_r, withdraw_r, days):
    """对选定时间范围内的数据进行模拟"""
    df = df.copy().reset_index(drop=True)
    
    # 基础指标
    df['Basis'] = df['Spot'] - df['Futures']
    df['Cycle_PnL_NoHedge'] = df['Spot'].diff(days) * q
    df['Cycle_Futures_PnL'] = -(df['Futures'].diff(days)) * q * ratio
    df['Cycle_PnL_Hedge'] = df['Cycle_PnL_NoHedge'] + df['Cycle_Futures_PnL']

    # 资金流模拟
    equity_list, margin_req_list = [], []
    cash_in_list, cash_out_list = [], []
    risk_degree_list = []

    current_price = df['Futures'].iloc[0]
    # 初始资金 = 初始保证金 * 警戒线倍数 (确保开始时不触发补仓)
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
# 4. 📊 主界面逻辑
# ==============================================================================
st.title("📊 企业套期保值资金风控看板")
st.markdown("---")

if uploaded_file is not None:
    # 1. 预加载
    raw_df, err = load_raw_data(uploaded_file)
    
    if err:
        st.error(err)
    else:
        # 2. 侧边栏添加时间范围选择器
        st.sidebar.subheader("📅 样本时间范围")
        min_date = raw_df['Date'].min().to_pydatetime()
        max_date = raw_df['Date'].max().to_pydatetime()
        
        # 让用户选择开始和结束日期
        time_range = st.sidebar.date_input(
            "选择分析时段",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date
        )

        # 检查是否选择了完整范围
        if isinstance(time_range, tuple) and len(time_range) == 2:
            start_date, end_date = time_range
            
            # 3. 过滤数据
            mask = (raw_df['Date'].dt.date >= start_date) & (raw_df['Date'].dt.date <= end_date)
            filtered_df = raw_df.loc[mask].copy()
            
            if len(filtered_df) < 2:
                st.warning("⚠️ 所选时间范围内数据量过少，请重新选择。")
            else:
                # 4. 运行模拟
                df = run_simulation(filtered_df, quantity, hedge_ratio, margin_rate, inject_ratio, withdraw_ratio, holding_days)

                # --- KPI 展现 ---
                col1, col2, col3, col4 = st.columns(4)
                total_inject = df['Cash_Injection'].sum() / 10000
                total_withdraw = df['Cash_Withdrawal'].sum() / 10000
                net_flow = total_withdraw - total_inject

                col1.metric("累计补入资金", f"{total_inject:.2f} 万")
                col2.metric("累计提取盈余", f"{total_withdraw:.2f} 万")
                col3.metric("资金净回流", f"{net_flow:.2f} 万")
                col4.metric("最新风险度", f"{df['Risk_Degree'].iloc[-1] * 100:.1f}%")

                # --- 图表展示 ---
                tab1, tab2, tab3 = st.tabs(["📉 价格与基差", "🏦 资金安全通道", "🛡️ 套保波动对比"])

                with tab1:
                    fig1, ax1 = plt.subplots(figsize=(10, 4))
                    ax1.plot(df['Date'], df['Spot'], label='现货价格', color='blue')
                    ax1.plot(df['Date'], df['Futures'], label='期货价格', color='orange', linestyle='--')
                    ax1.legend()
                    st.pyplot(fig1)

                with tab2:
                    fig2, ax2 = plt.subplots(figsize=(10, 4))
                    ax2.fill_between(df['Date'], df['Line_Inject']/10000, df['Line_Withdraw']/10000, color='gray', alpha=0.1, label='安全缓冲区')
                    ax2.plot(df['Date'], df['Account_Equity']/10000, color='green', label='账户权益(万元)')
                    ax2.legend()
                    st.pyplot(fig2)
                
                with tab3:
                    fig3, ax3 = plt.subplots(figsize=(10, 4))
                    ax3.plot(df['Date'], df['Value_Change_NoHedge']/10000, label='未套保资产波动', alpha=0.4)
                    ax3.plot(df['Date'], df['Value_Change_Hedged']/10000, label='套保后综合资产变动', color='green', linewidth=2)
                    ax3.legend()
                    st.pyplot(fig3)

                # 导出
                csv = df.to_csv(index=False).encode('utf-8-sig')
                st.download_button("📥 下载选定时间段分析报告 (CSV)", data=csv, file_name=f'hedge_report_{start_date}_{end_date}.csv')
        else:
            st.info("💡 请在侧边栏选择完整的 [开始日期] 和 [结束日期]。")

else:
    st.info("👆 请在左侧上传数据文件以开启分析。")

