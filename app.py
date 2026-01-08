import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import io
import platform

# ==============================================================================
# 🚀 界面定制 (严格保留原版 CSS)
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
# 2. 🎛️ 侧边栏参数 (已修复消失问题，并加入乘数逻辑)
# ==============================================================================
st.sidebar.header("🛠️ 参数配置面板")

# 数据上传组件
uploaded_file = st.sidebar.file_uploader("上传数据文件 (CSV)", type=['csv'])

st.sidebar.subheader("🏭 业务场景")

# 自变量拆分：手数 * 乘数
multiplier = st.sidebar.number_input("合约乘数 (每一手的数量)", value=10, step=1)

lots = st.sidebar.number_input("下单手数", value=3, step=1)

# 计算持仓总量用于后续逻辑
quantity = lots * multiplier 

st.sidebar.info(f"当前计算持仓总量: {quantity}")

hedge_ratio = st.sidebar.slider("套保比例 (1.0 = 100%)", 0.0, 1.2, 1.0, 0.1)

margin_rate = st.sidebar.number_input("保证金率 (0.12 = 12%)", value=0.12, step=0.01, format="%.2f")

st.sidebar.subheader("💰 资金区间管理")

inject_ratio = st.sidebar.number_input("补金警戒线 (倍数)", value=1.2, step=0.05)

withdraw_ratio = st.sidebar.number_input("提盈触发线 (倍数)", value=1.5, step=0.05)

st.sidebar.subheader("⏳ 模拟设置")

holding_days = st.sidebar.slider("库存周转/持仓周期 (天)", 7, 90, 30)

# ==============================================================================
# 3. 🧠 核心计算逻辑 (完全保留 app (2).py 原版公式)
# ==============================================================================
@st.cache_data
def process_data(df_input, q, ratio, m_rate, inject_r, withdraw_r, days):
    df = df_input.copy().reset_index(drop=True)
    
    # 基础基差与周期损益
    df['Basis'] = df['Spot'] - df['Futures']
    df['Cycle_PnL_NoHedge'] = df['Spot'].diff(days) * q
    df['Cycle_Futures_PnL'] = -(df['Futures'].diff(days)) * q * ratio
    df['Cycle_PnL_Hedge'] = df['Cycle_PnL_NoHedge'] + df['Cycle_Futures_PnL']

    # 列表初始化
    equity_list = []
    margin_req_list = []
    cash_in_list = []
    cash_out_list = []
    risk_degree_list = []
    
    current_price = df['Futures'].iloc[0]
    initial_equity = current_price * q * ratio * m_rate * inject_r
    current_equity = initial_equity

    # 逐行迭代模拟资金流
    for i in range(len(df)):
        price = df['Futures'].iloc[i]
        
        if i > 0:
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

    # 结果装载
    df['Account_Equity'] = equity_list
    df['Margin_Required'] = margin_req_list
    df['Cash_Injection'] = cash_in_list
    df['Cash_Withdrawal'] = cash_out_list
    df['Risk_Degree'] = risk_degree_list
    df['Line_Inject'] = df['Margin_Required'] * inject_r
    df['Line_Withdraw'] = df['Margin_Required'] * withdraw_r
    
    cum_net_cash = pd.Series(cash_out_list).cumsum() - pd.Series(cash_in_list).cumsum()
    base_asset = (df['Spot'].iloc[0] * q) + initial_equity
    
    df['Value_Change_NoHedge'] = (df['Spot'] - df['Spot'].iloc[0]) * q
    
    curr_asset = (df['Spot'] * q) + df['Account_Equity'] + cum_net_cash
    df['Value_Change_Hedged'] = curr_asset - base_asset
    
    return df

# ==============================================================================
# 4. 📊 主展示逻辑 (升级为 Plotly 交互图表)
# ==============================================================================
st.title("🛡️ 套期保值稳定性回测系统")

if uploaded_file:
    try:
        raw_df = pd.read_csv(uploaded_file, encoding='gbk')
    except:
        raw_df = pd.read_csv(uploaded_file, encoding='utf-8-sig')
    
    raw_df.columns = [str(c).strip() for c in raw_df.columns]
    col_time = next((c for c in raw_df.columns if '时间' in c or 'Date' in c), None)
    col_spot = next((c for c in raw_df.columns if '现货' in c), None)
    col_fut = next((c for c in raw_df.columns if ('期货' in c or '主力' in c) and '价格' in c), None)

    if col_time and col_spot and col_fut:
        raw_df = raw_df.rename(columns={col_time: 'Date', col_spot: 'Spot', col_fut: 'Futures'})
        raw_df['Date'] = pd.to_datetime(raw_df['Date'])
        for col in ['Spot', 'Futures']:
            raw_df[col] = pd.to_numeric(raw_df[col].astype(str).str.replace(',', ''), errors='coerce')
        raw_df = raw_df.sort_values('Date').reset_index(drop=True)

        min_d, max_d = raw_df['Date'].min().to_pydatetime(), raw_df['Date'].max().to_pydatetime()
        date_range = st.sidebar.date_input("分析起止时间", value=(min_d, max_d))

        if isinstance(date_range, tuple) and len(date_range) == 2:
            # 执行计算逻辑
            df = process_data(raw_df[(raw_df['Date'].dt.date >= date_range[0]) & (raw_df['Date'].dt.date <= date_range[1])], 
                             quantity, hedge_ratio, margin_rate, inject_ratio, withdraw_ratio, holding_days)

            # --- 原版指标显示 ---
            std_raw = df['Value_Change_NoHedge'].std() / 10000
            std_hedge = df['Value_Change_Hedged'].std() / 10000
            stability_boost = (1 - std_hedge / std_raw) * 100 if std_raw != 0 else 0
            
            max_loss_no = df['Value_Change_NoHedge'].min() / 10000
            max_loss_hedge = df['Value_Change_Hedged'].min() / 10000
            loss_saved = max_loss_hedge - max_loss_no 

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("现货波动风险 (标准差)", f"{std_raw:.2f} 万")
            c2.metric("套保后剩余波动", f"{std_hedge:.2f} 万", delta=f"降低 {stability_boost:.1f}%")
            c3.metric("累计调仓净额", f"{(df['Cash_Withdrawal'].sum() - df['Cash_Injection'].sum())/10000:.2f} 万")
            c4.metric("最大亏损修复额", f"{loss_saved:.2f} 万")

            # --- 交互式标签页 (解决 scipy 依赖报错问题) ---
            t1, t2, t3, t4 = st.tabs(["📉 价格基差监控", "🛡️ 对冲波动稳定性", "📊 风险概率分布", "🏦 资金通道监管"])

            with t1:
                # 价格基差监控 - 对应原版图1
                fig1 = go.Figure()
                fig1.add_trace(go.Scatter(x=df['Date'], y=df['Spot']/10000, name='现货', line=dict(color='blue')))
                fig1.add_trace(go.Scatter(x=df['Date'], y=df['Futures']/10000, name='期货', line=dict(color='orange', dash='dash')))
                fig1.add_trace(go.Scatter(x=df['Date'], y=df['Basis']/10000, name='基差(右轴)', fill='tozeroy', yaxis='y2', line=dict(width=0), opacity=0.3, fillcolor='gray'))
                fig1.update_layout(hovermode="x unified", yaxis=dict(title="价格 (万)"), yaxis2=dict(overlaying='y', side='right', showgrid=False))
                st.plotly_chart(fig1, use_container_width=True)

            with t2:
                # 对冲稳定性 - 对应原版图4
                fig2 = go.Figure()
                fig2.add_trace(go.Scatter(x=df['Date'], y=df['Value_Change_NoHedge']/10000, name='裸奔风险', line=dict(color='red', width=1), opacity=0.3))
                fig2.add_trace(go.Scatter(x=df['Date'], y=df['Value_Change_Hedged']/10000, name='对冲后稳态', line=dict(color='green', width=2)))
                fig2.update_layout(hovermode="x unified", yaxis=dict(title="价值变动 (万)"))
                st.plotly_chart(fig2, use_container_width=True)

            with t3:
                # 风险分布 - 修复原版 scipy 报错
                fig3 = go.Figure()
                fig3.add_trace(go.Histogram(x=df['Cycle_PnL_NoHedge']/10000, name='未套保', marker_color='red', opacity=0.3))
                fig3.add_trace(go.Histogram(x=df['Cycle_PnL_Hedge']/10000, name='套保后', marker_color='green', opacity=0.5))
                fig3.update_layout(barmode='overlay', xaxis=dict(title="盈亏金额 (万)"))
                st.plotly_chart(fig3, use_container_width=True)

            with t4:
                # 资金监管 - 对应原版图3
                fig4 = go.Figure()
                fig4.add_trace(go.Scatter(x=df['Date'], y=df['Line_Withdraw']/10000, name='提盈线', line=dict(color='rgba(0,0,255,0.1)', dash='dot')))
                fig4.add_trace(go.Scatter(x=df['Date'], y=df['Line_Inject']/10000, name='补金线', line=dict(color='rgba(255,0,0,0.1)', dash='dot'), fill='tonexty', fillcolor='rgba(128,128,128,0.05)'))
                fig4.add_trace(go.Scatter(x=df['Date'], y=df['Account_Equity']/10000, name='权益', line=dict(color='black', width=1.5)))
                
                # 标注操作事件点
                inj_ev = df[df['Cash_Injection']>0]
                wit_ev = df[df['Cash_Withdrawal']>0]
                fig4.add_trace(go.Scatter(x=inj_ev['Date'], y=inj_ev['Account_Equity']/10000, mode='markers', name='补仓', marker=dict(color='red', symbol='triangle-up', size=10)))
                fig4.add_trace(go.Scatter(x=wit_ev['Date'], y=wit_ev['Account_Equity']/10000, mode='markers', name='出金', marker=dict(color='blue', symbol='triangle-down', size=10)))
                fig4.update_layout(hovermode="x unified", yaxis=dict(title="金额 (万)"))
                st.plotly_chart(fig4, use_container_width=True)

            # --- 原版分析结论 ---
            st.markdown("---")
            st.subheader("📝 稳定性分析结论")
            sc1, sc2 = st.columns(2)
            with sc1:
                st.write(f"✅ **风险对冲质量**：通过套保，资产净值的波动幅度被压制在了现货波动的 **{100-stability_boost:.1f}%** 范围内。")
                st.write(f"✅ **极端生存能力**：在回测期内最不利的价格波动下，套保方案成功挽救了约 **{loss_saved:.2f} 万元** 的潜在损失。")
            with sc2:
                st.write(f"✅ **资金运营频率**：系统平均每 **{len(df)/(len(inj_ev)+len(wit_ev)+1):.1f}** 天触发一次资金调度。")
                st.write(f"✅ **收益确定性**：套保后的盈亏分布（见标签3）明显向中心靠拢，大幅降低了企业经营的“意外”风险。")

            # 导出功能
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='回测详情')
            st.download_button("📥 下载完整回测数据", data=output.getvalue(), file_name='套保回测报告.xlsx')
else:
    st.info("👆 请上传包含现货和期货价格的 CSV 数据文件开启系统分析。")





