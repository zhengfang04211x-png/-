import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import io
import platform

# ==============================================================================
# 🚀 界面定制 (全量保留原始样式)
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
# 1. 🎨 页面基本设置
# ==============================================================================
st.set_page_config(page_title="套期保值稳定性回测系统", layout="wide", page_icon="🛡️")

# ==============================================================================
# 2. 🎛️ 侧边栏：参数配置面板 (严格展开，不合并行)
# ==============================================================================
st.sidebar.header("🛠️ 参数配置面板")

uploaded_file = st.sidebar.file_uploader("上传数据文件 (CSV)", type=['csv'])

st.sidebar.subheader("🏭 业务场景")

# 拆分原有的持仓数量为 手数 * 乘数，方便企业核算
multiplier = st.sidebar.number_input("合约乘数 (每一手代表的数量)", value=10, step=1)

lots = st.sidebar.number_input("下单手数", value=3, step=1)

# 自动计算总量
quantity = lots * multiplier 

st.sidebar.info(f"实际套保总量: {quantity}")

hedge_ratio = st.sidebar.slider("套保比例 (1.0 = 100%)", 0.0, 1.2, 1.0, 0.1)

margin_rate = st.sidebar.number_input("保证金率 (0.12 = 12%)", value=0.12, step=0.01, format="%.2f")

st.sidebar.subheader("💰 资金区间管理")

inject_ratio = st.sidebar.number_input("补金警戒线 (倍数)", value=1.2, step=0.05)

withdraw_ratio = st.sidebar.number_input("提盈触发线 (倍数)", value=1.5, step=0.05)

st.sidebar.subheader("⏳ 模拟设置")

holding_days = st.sidebar.slider("库存周转/持仓周期 (天)", 7, 90, 30)

# ==============================================================================
# 3. 🧠 核心计算逻辑 (完全保留原版逻辑，不压缩行)
# ==============================================================================
@st.cache_data
def process_data(df_input, q, ratio, m_rate, inject_r, withdraw_r, days):
    df = df_input.copy().reset_index(drop=True)

    # 基础基差与周期损益计算
    df['Basis'] = df['Spot'] - df['Futures']
    df['Cycle_PnL_NoHedge'] = df['Spot'].diff(days) * q
    df['Cycle_Futures_PnL'] = -(df['Futures'].diff(days)) * q * ratio
    df['Cycle_PnL_Hedge'] = df['Cycle_PnL_NoHedge'] + df['Cycle_Futures_PnL']

    # 资金流转初始化
    equity_list = []
    margin_req_list = []
    cash_in_list = []
    cash_out_list = []
    risk_degree_list = []

    current_price = df['Futures'].iloc[0]
    initial_equity = current_price * q * ratio * m_rate * inject_r
    current_equity = initial_equity

    # 模拟逐日资金变动
    for i in range(len(df)):
        price = df['Futures'].iloc[i]
        
        if i > 0:
            # 这里的计算严格按照你的原始逻辑
            current_equity += -(price - df['Futures'].iloc[i - 1]) * q * ratio

        req_margin = price * q * ratio * m_rate
        margin_req_list.append(req_margin)

        thresh_low = req_margin * inject_r
        thresh_high = req_margin * withdraw_r

        in_amt = 0
        out_amt = 0

        if current_equity < thresh_low:
            in_amt = thresh_low - current_equity
            current_equity += in_amt
        elif current_equity > thresh_high:
            out_amt = current_equity - thresh_high
            current_equity -= out_amt

        cash_in_list.append(in_amt)
        cash_out_list.append(out_amt)
        equity_list.append(current_equity)
        
        if req_margin > 0:
            risk_degree_list.append(current_equity / req_margin)
        else:
            risk_degree_list.append(0)

    # 填充结果到 DataFrame
    df['Account_Equity'] = equity_list
    df['Margin_Required'] = margin_req_list
    df['Cash_Injection'] = cash_in_list
    df['Cash_Withdrawal'] = cash_out_list
    df['Risk_Degree'] = risk_degree_list
    df['Line_Inject'] = df['Margin_Required'] * inject_r
    df['Line_Withdraw'] = df['Margin_Required'] * withdraw_r

    # 资产总价值变动计算
    cum_net_cash = pd.Series(cash_out_list).cumsum() - pd.Series(cash_in_list).cumsum()
    base_asset = (df['Spot'].iloc[0] * q) + initial_equity
    
    df['Value_Change_NoHedge'] = (df['Spot'] - df['Spot'].iloc[0]) * q
    
    current_combined_asset = (df['Spot'] * q) + df['Account_Equity'] + cum_net_cash
    df['Value_Change_Hedged'] = current_combined_asset - base_asset

    return df

# ==============================================================================
# 4. 📊 主界面展示展示 (升级为全交互图表，保留所有分析结论)
# ==============================================================================
st.title("📊 企业套期保值资金风控看板")
st.markdown("---")

if uploaded_file is not None:
    # 数据加载
    try:
        raw_df = pd.read_csv(uploaded_file, encoding='gbk')
    except:
        raw_df = pd.read_csv(uploaded_file, encoding='utf-8-sig')
    
    # 清洗列名
    raw_df.columns = [str(c).strip() for c in raw_df.columns]
    
    # 自动定位关键列
    col_time = next((c for c in raw_df.columns if '时间' in c or 'Date' in c), None)
    col_spot = next((c for c in raw_df.columns if '现货' in c), None)
    col_fut = next((c for c in raw_df.columns if ('期货' in c or '主力' in c) and '价格' in c), None)

    if col_time and col_spot and col_fut:
        # 重命名与预处理
        raw_df = raw_df.rename(columns={col_time: 'Date', col_spot: 'Spot', col_fut: 'Futures'})
        raw_df['Date'] = pd.to_datetime(raw_df['Date'])
        
        for col in ['Spot', 'Futures']:
            raw_df[col] = pd.to_numeric(raw_df[col].astype(str).str.replace(',', ''), errors='coerce')
        
        raw_df = raw_df.sort_values('Date').reset_index(drop=True)

        # 时间筛选
        min_date = raw_df['Date'].min().to_pydatetime()
        max_date = raw_df['Date'].max().to_pydatetime()
        date_range = st.sidebar.date_input("选择回测时间段", value=(min_date, max_date))

        if isinstance(date_range, tuple) and len(date_range) == 2:
            mask = (raw_df['Date'].dt.date >= date_range[0]) & (raw_df['Date'].dt.date <= date_range[1])
            filtered_df = raw_df.loc[mask]
            
            # 调用计算核心
            df = process_data(filtered_df, quantity, hedge_ratio, margin_rate, inject_ratio, withdraw_ratio, holding_days)

            # --- 指标看板 ---
            col1, col2, col3, col4 = st.columns(4)
            
            std_raw = df['Value_Change_NoHedge'].std() / 10000
            std_hedge = df['Value_Change_Hedged'].std() / 10000
            stability_improvement = (1 - std_hedge / std_raw) * 100 if std_raw != 0 else 0
            
            total_cash_in = df['Cash_Injection'].sum() / 10000
            total_cash_out = df['Cash_Withdrawal'].sum() / 10000
            
            col1.metric("现货风险波动 (万)", f"{std_raw:.2f}")
            col2.metric("套保后波动 (万)", f"{std_hedge:.2f}", delta=f"下降 {stability_improvement:.1f}%")
            col3.metric("累计调仓净额 (万)", f"{(total_cash_out - total_cash_in):.2f}")
            col4.metric("最新账户风险度", f"{df['Risk_Degree'].iloc[-1] * 100:.1f}%")

            # --- 交互式标签页 (Plotly 实现) ---
            tab1, tab2, tab3, tab4 = st.tabs(["📉 价格基差监控", "🛡️ 对冲波动稳定性", "📊 风险概率分布分布", "🏦 资金通道监管"])

            with tab1:
                st.subheader("期现价格走势与基差分布")
                fig1 = go.Figure()
                fig1.add_trace(go.Scatter(x=df['Date'], y=df['Spot'], name='现货价格', line=dict(color='#1f77b4', width=2)))
                fig1.add_trace(go.Scatter(x=df['Date'], y=df['Futures'], name='期货价格', line=dict(color='#ff7f0e', dash='dash')))
                # 基差显示在次坐标轴
                fig1.add_trace(go.Scatter(x=df['Date'], y=df['Basis'], name='基差(右轴)', fill='tozeroy', yaxis='y2', line=dict(width=0), opacity=0.3, fillcolor='rgba(128,128,128,0.5)'))
                fig1.update_layout(hovermode="x unified", height=500, yaxis=dict(title="价格"), yaxis2=dict(overlaying='y', side='right', showgrid=False, title="基差金额"))
                st.plotly_chart(fig1, use_container_width=True)

            with tab2:
                st.subheader("未套保 vs 套保后 资产损益变动对比")
                fig2 = go.Figure()
                fig2.add_trace(go.Scatter(x=df['Date'], y=df['Value_Change_NoHedge']/10000, name='未套保损益(万)', line=dict(color='red', width=1.5), opacity=0.4))
                fig2.add_trace(go.Scatter(x=df['Date'], y=df['Value_Change_Hedged']/10000, name='套保后净值(万)', line=dict(color='green', width=3)))
                fig2.update_layout(hovermode="x unified", height=500, yaxis_title="金额 (万元)")
                st.plotly_chart(fig2, use_container_width=True)

            with tab3:
                st.subheader(f"持仓{holding_days}天周期 盈亏频率分布")
                fig3 = go.Figure()
                fig3.add_trace(go.Histogram(x=df['Cycle_PnL_NoHedge']/10000, name='未套保分布', marker_color='red', opacity=0.4))
                fig3.add_trace(go.Histogram(x=df['Cycle_PnL_Hedge']/10000, name='套保后分布', marker_color='green', opacity=0.6))
                fig3.update_layout(barmode='overlay', height=500, xaxis_title="单周期盈亏 (万元)", yaxis_title="发生频数")
                st.plotly_chart(fig3, use_container_width=True)

            with tab4:
                st.subheader("期货账户权益通道与调仓记录")
                fig4 = go.Figure()
                fig4.add_trace(go.Scatter(x=df['Date'], y=df['Line_Withdraw']/10000, name='提盈触发线', line=dict(color='rgba(0,0,255,0.2)', dash='dot')))
                fig4.add_trace(go.Scatter(x=df['Date'], y=df['Line_Inject']/10000, name='补金警戒线', line=dict(color='rgba(255,0,0,0.2)', dash='dot'), fill='tonexty', fillcolor='rgba(128,128,128,0.05)'))
                fig4.add_trace(go.Scatter(x=df['Date'], y=df['Account_Equity']/10000, name='实时权益', line=dict(color='black', width=2)))
                
                # 标注具体的补仓和提盈点
                inj_points = df[df['Cash_Injection'] > 0]
                wit_points = df[df['Cash_Withdrawal'] > 0]
                
                fig4.add_trace(go.Scatter(x=inj_points['Date'], y=inj_points['Account_Equity']/10000, mode='markers', name='补仓动作', marker=dict(color='red', symbol='triangle-up', size=10)))
                fig4.add_trace(go.Scatter(x=wit_points['Date'], y=wit_points['Account_Equity']/10000, mode='markers', name='提盈动作', marker=dict(color='blue', symbol='triangle-down', size=10)))
                
                fig4.update_layout(hovermode="x unified", height=500, yaxis_title="账户资金 (万元)")
                st.plotly_chart(fig4, use_container_width=True)

            # --- 摘要分析结论 (严格保留原版文案) ---
            st.markdown("---")
            st.subheader("📝 回测综合分析报告")
            
            c_left, c_right = st.columns(2)
            
            with c_left:
                st.success(f"✅ **风险抵御评估**：本套保方案成功抵消了市场约 **{stability_improvement:.1f}%** 的价格波动风险。")
                max_drawdown = (df['Value_Change_Hedged'].min() - df['Value_Change_NoHedge'].min()) / 10000
                st.info(f"✅ **极端生存能力**：在最不利行情下，套保头寸比裸奔多保住了约 **{max_drawdown:.2f} 万元** 的资产价值。")
            
            with c_right:
                total_ops = len(inj_points) + len(wit_points)
                st.warning(f"🏦 **资金运营评估**：回测期内共触发 **{total_ops}** 次资金调度（补金/提盈）。")
                st.info(f"🏦 **套保效率**：当前套保比例为 {hedge_ratio*100:.0f}%，盈亏分布显著向中心收拢，经营确定性大幅提升。")

            # 导出功能
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='回测数据详情')
            st.download_button("📥 导出回测分析详情 (Excel)", data=output.getvalue(), file_name='Backtest_Full_Report.xlsx')

else:
    st.info("💡 请在左侧上传包含‘现货价格’与‘期货价格’的历史数据 CSV 文件。")






