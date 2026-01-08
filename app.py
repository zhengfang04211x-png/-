import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from scipy import stats
import io
import platform

# ==============================================================================
# 🚀 界面定制 (全量保留自 app (2).py)
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
# 2. 🎛️ 侧边栏参数 (仅修改持仓数量为乘数联动，其余文案不动)
# ==============================================================================
st.sidebar.header("🛠️ 参数配置面板")
uploaded_file = st.sidebar.file_uploader("上传数据文件 (CSV)", type=['csv'])

st.sidebar.subheader("🏭 业务场景")
# 原版 quantity 替换为 乘数 * 手数
multiplier = st.sidebar.number_input("合约乘数 (一手的数量)", value=10, step=1)
lots = st.sidebar.number_input("下单手数", value=3, step=1)
quantity = lots * multiplier 

hedge_ratio = st.sidebar.slider("套保比例 (1.0 = 100%)", 0.0, 1.2, 1.0, 0.1)
margin_rate = st.sidebar.number_input("保证金率 (0.12 = 12%)", value=0.12, step=0.01, format="%.2f")

st.sidebar.subheader("💰 资金区间管理")
inject_ratio = st.sidebar.number_input("补金警戒线 (倍数)", value=1.2, step=0.05)
withdraw_ratio = st.sidebar.number_input("提盈触发线 (倍数)", value=1.5, step=0.05)

st.sidebar.subheader("⏳ 模拟设置")
holding_days = st.sidebar.slider("库存周转/持仓周期 (天)", 7, 90, 30)

# ==============================================================================
# 3. 🧠 核心计算逻辑 (严格从 app (2).py 复制，不改一个符号)
# ==============================================================================
@st.cache_data
def process_data(df_input, q, ratio, m_rate, inject_r, withdraw_r, days):
    df = df_input.copy().reset_index(drop=True)
    df['Basis'] = df['Spot'] - df['Futures']
    df['Cycle_PnL_NoHedge'] = df['Spot'].diff(days) * q
    df['Cycle_Futures_PnL'] = -(df['Futures'].diff(days)) * q * ratio
    df['Cycle_PnL_Hedge'] = df['Cycle_PnL_NoHedge'] + df['Cycle_Futures_PnL']

    equity_list, margin_req_list, cash_in_list, cash_out_list, risk_degree_list = [], [], [], [], []
    current_price = df['Futures'].iloc[0]
    initial_equity = current_price * q * ratio * m_rate * inject_r
    current_equity = initial_equity

    for i in range(len(df)):
        price = df['Futures'].iloc[i]
        if i > 0:
            current_equity += -(price - df['Futures'].iloc[i - 1]) * q * ratio
        req_margin = price * q * ratio * m_rate
        margin_req_list.append(req_margin)
        thresh_low, thresh_high = req_margin * inject_r, req_margin * withdraw_r
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

    df['Account_Equity'], df['Margin_Required'] = equity_list, margin_req_list
    df['Cash_Injection'], df['Cash_Withdrawal'] = cash_in_list, cash_out_list
    df['Risk_Degree'] = risk_degree_list
    df['Line_Inject'], df['Line_Withdraw'] = df['Margin_Required'] * inject_r, df['Margin_Required'] * withdraw_r
    
    cum_net_cash = pd.Series(cash_out_list).cumsum() - pd.Series(cash_in_list).cumsum()
    base_asset = (df['Spot'].iloc[0] * q) + initial_equity
    curr_asset = (df['Spot'] * q) + df['Account_Equity'] + cum_net_cash
    df['Value_Change_NoHedge'] = (df['Spot'] - df['Spot'].iloc[0]) * q
    df['Value_Change_Hedged'] = curr_asset - base_asset
    return df

def create_kde_trace(data, name, color):
    """创建KDE密度图轨迹"""
    # 去除NaN值
    clean_data = data.dropna()
    
    if len(clean_data) < 2:
        return None
    
    # 计算KDE
    kde = stats.gaussian_kde(clean_data)
    x_range = np.linspace(clean_data.min() * 1.1, clean_data.max() * 1.1, 500)
    y_kde = kde(x_range)
    
    # 计算统计指标
    mean_val = clean_data.mean()
    median_val = clean_data.median()
    std_val = clean_data.std()
    
    # 创建KDE曲线
    trace = go.Scatter(
        x=x_range,
        y=y_kde,
        mode='lines',
        name=name,
        line=dict(color=color, width=2),
        fill='tozeroy',
        fillcolor=f'rgba({color[4:-1]}, 0.2)' if color.startswith('rgb') else f'rgba{tuple(int(color.lstrip("#")[i:i+2], 16) for i in (0, 2, 4)) + (0.2,)}',
        hovertemplate=f'<b>{name}</b><br>金额: %{{x:,.0f}}元<br>概率密度: %{{y:.4f}}<extra></extra>'
    )
    
    return trace, mean_val, median_val, std_val

# ==============================================================================
# 4. 📊 展示逻辑 (优化版)
# ==============================================================================
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
        date_range = st.sidebar.date_input("分析起止时间", value=(min_d, max_d), min_value=min_d, max_value=max_d)

        if isinstance(date_range, tuple) and len(date_range) == 2:
            df = process_data(raw_df[(raw_df['Date'].dt.date >= date_range[0]) & (raw_df['Date'].dt.date <= date_range[1])], 
                             quantity, hedge_ratio, margin_rate, inject_ratio, withdraw_ratio, holding_days)

            # --- 原版 Metric 数值计算 ---
            std_raw = df['Value_Change_NoHedge'].std() / 10000
            std_hedge = df['Value_Change_Hedged'].std() / 10000
            stability_boost = (1 - std_hedge / std_raw) * 100 if std_raw != 0 else 0
            max_loss_no = df['Value_Change_NoHedge'].min() / 10000
            max_loss_hedge = df['Value_Change_Hedged'].min() / 10000
            loss_saved = max_loss_hedge - max_loss_no 

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("现货波动风险 (标准差)", f"{std_raw:.2f} 万")
            c2.metric("套保后剩余波动", f"{std_hedge:.2f} 万", delta=f"降低 {stability_boost:.1f}%", delta_color="normal")
            c3.metric("累计调仓净额", f"{(df['Cash_Withdrawal'].sum() - df['Cash_Injection'].sum())/10000:.2f} 万")
            c4.metric("最大亏损修复额", f"{loss_saved:.2f} 万")

            # --- 原版标签页 Tab 顺序 ---
            t1, t2, t3, t4 = st.tabs(["📉 价格基差监控", "🛡️ 对冲波动稳定性", "📊 风险概率分布", "🏦 资金通道监管"])

            with t1:
                # 价格基差监控 - Plotly 版
                fig1 = go.Figure()
                fig1.add_trace(go.Scatter(x=df['Date'], y=df['Spot']/10000, name='现货', line=dict(color='blue')))
                fig1.add_trace(go.Scatter(x=df['Date'], y=df['Futures']/10000, name='期货', line=dict(color='orange', dash='dash')))
                fig1.add_trace(go.Scatter(x=df['Date'], y=df['Basis']/10000, name='基差', fill='tozeroy', yaxis='y2', line=dict(width=0), opacity=0.2, fillcolor='gray'))
                fig1.update_layout(hovermode="x unified", height=400, margin=dict(t=20, b=20),
                                 yaxis=dict(title="价格 (万)"), yaxis2=dict(overlaying='y', side='right', showgrid=False))
                st.plotly_chart(fig1, use_container_width=True)

            with t2:
                # 对冲波动稳定性 - Plotly 版
                fig2 = go.Figure()
                fig2.add_trace(go.Scatter(x=df['Date'], y=df['Value_Change_NoHedge']/10000, name='裸奔风险', line=dict(color='red', width=1), opacity=0.3))
                fig2.add_trace(go.Scatter(x=df['Date'], y=df['Value_Change_Hedged']/10000, name='对冲后稳态', line=dict(color='green', width=2)))
                fig2.update_layout(hovermode="x unified", height=400, margin=dict(t=20, b=20), yaxis=dict(title="价值变动 (万)"))
                st.plotly_chart(fig2, use_container_width=True)

            with t3:
                # 风险概率分布 - 改为KDE密度图 + 统计标记
                fig3 = go.Figure()
                
                # 创建KDE密度图
                kde_nohedge = create_kde_trace(df['Cycle_PnL_NoHedge'], '未套保', 'rgb(255, 0, 0)')
                kde_hedge = create_kde_trace(df['Cycle_PnL_Hedge'], '套保后', 'rgb(0, 128, 0)')
                
                if kde_nohedge and kde_hedge:
                    trace_nohedge, mean_nohedge, median_nohedge, std_nohedge = kde_nohedge
                    trace_hedge, mean_hedge, median_hedge, std_hedge = kde_hedge
                    
                    fig3.add_trace(trace_nohedge)
                    fig3.add_trace(trace_hedge)
                    
                    # 添加均值线标记
                    fig3.add_vline(x=mean_nohedge, line=dict(color='red', width=1, dash='dash'), 
                                 annotation_text=f"均值: {mean_nohedge/10000:.1f}万", 
                                 annotation_position="top right")
                    fig3.add_vline(x=mean_hedge, line=dict(color='green', width=1, dash='dash'), 
                                 annotation_text=f"均值: {mean_hedge/10000:.1f}万", 
                                 annotation_position="top left")
                    
                    # 添加标准差区域
                    fig3.add_vrect(x0=mean_nohedge-std_nohedge, x1=mean_nohedge+std_nohedge,
                                 fillcolor="red", opacity=0.1, line_width=0,
                                 annotation_text=f"未套保±1σ", annotation_position="top")
                    fig3.add_vrect(x0=mean_hedge-std_hedge, x1=mean_hedge+std_hedge,
                                 fillcolor="green", opacity=0.1, line_width=0,
                                 annotation_text=f"套保后±1σ", annotation_position="bottom")
                    
                    # 添加0线标记
                    fig3.add_vline(x=0, line=dict(color='black', width=1, dash='dot'),
                                 annotation_text="盈亏平衡点")
                    
                    # 添加统计摘要
                    fig3.add_annotation(
                        x=0.02, y=0.98,
                        xref="paper", yref="paper",
                        text=f"<b>统计摘要:</b><br>未套保: μ={mean_nohedge/10000:.1f}万, σ={std_nohedge/10000:.1f}万<br>套保后: μ={mean_hedge/10000:.1f}万, σ={std_hedge/10000:.1f}万<br>波动降低: {(1-std_hedge/std_nohedge)*100:.1f}%",
                        showarrow=False,
                        align="left",
                        bordercolor="black",
                        borderwidth=1,
                        borderpad=4,
                        bgcolor="white",
                        opacity=0.8
                    )
                
                fig3.update_layout(
                    title="风险概率密度分布 (KDE)",
                    xaxis_title="盈亏金额 (元)",
                    yaxis_title="概率密度",
                    height=500,
                    hovermode="x",
                    showlegend=True,
                    legend=dict(
                        yanchor="top",
                        y=0.99,
                        xanchor="left",
                        x=0.01
                    )
                )
                st.plotly_chart(fig3, use_container_width=True)
                
                # 添加分布特征说明
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("未套保波动率", f"{df['Cycle_PnL_NoHedge'].std()/10000:.2f}万")
                with col2:
                    st.metric("套保后波动率", f"{df['Cycle_PnL_Hedge'].std()/10000:.2f}万", 
                             delta=f"降低{(1-df['Cycle_PnL_Hedge'].std()/df['Cycle_PnL_NoHedge'].std())*100:.1f}%")
                with col3:
                    st.metric("极端风险降低", f"{(df['Cycle_PnL_NoHedge'].quantile(0.05)-df['Cycle_PnL_Hedge'].quantile(0.05))/10000:.2f}万")

            with t4:
                # 资金通道监管 - 优化版
                fig4 = go.Figure()
                
                # 背景区域
                fig4.add_trace(go.Scatter(
                    x=df['Date'], 
                    y=df['Line_Withdraw']/10000, 
                    name='提盈线', 
                    line=dict(color='gray', dash='dot'), 
                    opacity=0.3
                ))
                fig4.add_trace(go.Scatter(
                    x=df['Date'], 
                    y=df['Line_Inject']/10000, 
                    name='补金线', 
                    line=dict(color='gray', dash='dot'), 
                    fill='tonexty', 
                    fillcolor='rgba(255, 165, 0, 0.1)',
                    opacity=0.3
                ))
                
                # 账户权益主线
                fig4.add_trace(go.Scatter(
                    x=df['Date'], 
                    y=df['Account_Equity']/10000, 
                    name='账户权益', 
                    line=dict(color='black', width=2),
                    fill='tonexty',
                    fillcolor='rgba(0, 100, 255, 0.1)'
                ))
                
                # 保证金要求线
                fig4.add_trace(go.Scatter(
                    x=df['Date'], 
                    y=df['Margin_Required']/10000, 
                    name='保证金要求', 
                    line=dict(color='purple', width=1, dash='dash'),
                    opacity=0.7
                ))
                
                # 提取补金和提盈事件
                inj_events = df[df['Cash_Injection'] > 0]
                wit_events = df[df['Cash_Withdrawal'] > 0]
                
                # 补金点 - 使用红色三角形
                if not inj_events.empty:
                    fig4.add_trace(go.Scatter(
                        x=inj_events['Date'], 
                        y=inj_events['Account_Equity']/10000,
                        mode='markers+text',
                        name='补金点',
                        marker=dict(
                            color='red',
                            symbol='triangle-up',
                            size=15,
                            line=dict(color='darkred', width=2)
                        ),
                        text=[f"+{amt/10000:.1f}万" for amt in inj_events['Cash_Injection']],
                        textposition="top center",
                        textfont=dict(color='red', size=10),
                        hovertemplate='<b>补金事件</b><br>时间: %{x}<br>权益: %{y:.1f}万<br>补金金额: %{text}<extra></extra>'
                    ))
                
                # 提盈点 - 使用绿色三角形
                if not wit_events.empty:
                    fig4.add_trace(go.Scatter(
                        x=wit_events['Date'], 
                        y=wit_events['Account_Equity']/10000,
                        mode='markers+text',
                        name='提盈点',
                        marker=dict(
                            color='green',
                            symbol='triangle-down',
                            size=15,
                            line=dict(color='darkgreen', width=2)
                        ),
                        text=[f"-{amt/10000:.1f}万" for amt in wit_events['Cash_Withdrawal']],
                        textposition="bottom center",
                        textfont=dict(color='green', size=10),
                        hovertemplate='<b>提盈事件</b><br>时间: %{x}<br>权益: %{y:.1f}万<br>提盈金额: %{text}<extra></extra>'
                    ))
                
                # 添加关键事件统计
                total_injections = inj_events['Cash_Injection'].sum()/10000
                total_withdrawals = wit_events['Cash_Withdrawal'].sum()/10000
                
                fig4.add_annotation(
                    x=0.02, y=0.98,
                    xref="paper", yref="paper",
                    text=f"<b>资金调度统计:</b><br>补金次数: {len(inj_events)}次<br>提盈次数: {len(wit_events)}次<br>净流出: {(total_withdrawals-total_injections):.1f}万",
                    showarrow=False,
                    align="left",
                    bordercolor="black",
                    borderwidth=1,
                    borderpad=4,
                    bgcolor="white",
                    opacity=0.8
                )
                
                fig4.update_layout(
                    title="资金通道监管 - 账户权益与资金调度",
                    hovermode="x unified",
                    height=500,
                    yaxis=dict(title="金额 (万)"),
                    showlegend=True,
                    legend=dict(
                        orientation="h",
                        yanchor="bottom",
                        y=1.02,
                        xanchor="right",
                        x=1
                    )
                )
                st.plotly_chart(fig4, use_container_width=True)
                
                # 资金调度详情表格
                if not inj_events.empty or not wit_events.empty:
                    st.subheader("📋 资金调度明细")
                    event_data = []
                    
                    for idx, row in inj_events.iterrows():
                        event_data.append({
                            '时间': row['Date'],
                            '类型': '补金',
                            '金额(万)': row['Cash_Injection']/10000,
                            '账户权益(万)': row['Account_Equity']/10000,
                            '触发原因': '账户权益低于补金警戒线'
                        })
                    
                    for idx, row in wit_events.iterrows():
                        event_data.append({
                            '时间': row['Date'],
                            '类型': '提盈',
                            '金额(万)': row['Cash_Withdrawal']/10000,
                            '账户权益(万)': row['Account_Equity']/10000,
                            '触发原因': '账户权益高于提盈触发线'
                        })
                    
                    if event_data:
                        event_df = pd.DataFrame(event_data).sort_values('时间')
                        st.dataframe(event_df, use_container_width=True)

            # --- 原版摘要分析文本 ---
            st.markdown("---")
            st.subheader("📝 稳定性分析结论")
            sc1, sc2 = st.columns(2)
            with sc1:
                st.write(f"✅ **风险对冲质量**：通过套保，资产净值的波动幅度被压制在了现货波动的 **{100-stability_boost:.1f}%** 范围内。")
                st.write(f"✅ **极端生存能力**：在回测期内最不利的价格波动下，套保方案成功挽救了约 **{loss_saved:.2f} 万元** 的潜在损失。")
            with sc2:
                st.write(f"✅ **资金运营频率**：系统平均每 **{len(df)/(len(inj_events)+len(wit_events)+1):.1f}** 天触发一次资金调度，操作频率处于合理区间。")
                st.write(f"✅ **收益确定性**：套保后的盈亏分布明显向中心靠拢，大幅降低了企业经营的"意外"风险。")

            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='回测数据')
                # 添加资金调度明细
                if 'event_df' in locals():
                    event_df.to_excel(writer, index=False, sheet_name='资金调度明细')
            st.download_button("📥 下载完整回测数据", data=output.getvalue(), file_name='套保回测报告.xlsx')
else:
    st.info("👆 请上传 CSV 数据文件开启系统分析。")










