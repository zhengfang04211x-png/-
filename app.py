import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from scipy import stats
import io
import platform
from plotly.subplots import make_subplots

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

# ==============================================================================
# 4. 📊 展示逻辑 (优化版 - 美观设计)
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

            # 提取补金和提盈事件
            inj_events = df[df['Cash_Injection'] > 0]
            wit_events = df[df['Cash_Withdrawal'] > 0]
            
            # --- 原版 Metric 数值计算 ---
            std_raw = df['Value_Change_NoHedge'].std() / 10000
            std_hedge = df['Value_Change_Hedged'].std() / 10000
            stability_boost = (1 - std_hedge / std_raw) * 100 if std_raw != 0 else 0
            max_loss_no = df['Value_Change_NoHedge'].min() / 10000
            max_loss_hedge = df['Value_Change_Hedged'].min() / 10000
            loss_saved = max_loss_hedge - max_loss_no 

            # 使用卡片式布局展示指标
            st.markdown("""
            <style>
            .metric-card {
                background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
                border-radius: 10px;
                padding: 15px;
                margin-bottom: 10px;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            }
            </style>
            """, unsafe_allow_html=True)
            
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.metric("现货波动风险 (标准差)", f"{std_raw:.2f} 万")
                st.markdown('</div>', unsafe_allow_html=True)
            with c2:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.metric("套保后剩余波动", f"{std_hedge:.2f} 万", delta=f"降低 {stability_boost:.1f}%", delta_color="inverse")
                st.markdown('</div>', unsafe_allow_html=True)
            with c3:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.metric("累计调仓净额", f"{(df['Cash_Withdrawal'].sum() - df['Cash_Injection'].sum())/10000:.2f} 万")
                st.markdown('</div>', unsafe_allow_html=True)
            with c4:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.metric("最大亏损修复额", f"{loss_saved:.2f} 万", delta_color="normal")
                st.markdown('</div>', unsafe_allow_html=True)

            # --- 标签页设计 ---
            t1, t2, t3, t4 = st.tabs(["📉 价格基差监控", "🛡️ 对冲波动稳定性", "📊 风险概率分布", "🏦 资金通道监管"])

            with t1:
                # 价格基差监控 - 现代设计
                fig1 = go.Figure()
                
                # 添加现货价格区域
                fig1.add_trace(go.Scatter(
                    x=df['Date'], y=df['Spot']/10000, 
                    name='现货价格', 
                    line=dict(color='#2E86AB', width=3),
                    fill=None,
                    hovertemplate='<b>现货价格</b><br>时间: %{x}<br>价格: %{y:.2f}万<extra></extra>'
                ))
                
                # 添加期货价格线
                fig1.add_trace(go.Scatter(
                    x=df['Date'], y=df['Futures']/10000, 
                    name='期货价格', 
                    line=dict(color='#F24236', width=3, dash='dash'),
                    hovertemplate='<b>期货价格</b><br>时间: %{x}<br>价格: %{y:.2f}万<extra></extra>'
                ))
                
                # 添加基差区域（使用副坐标轴）
                fig1.add_trace(go.Scatter(
                    x=df['Date'], y=df['Basis']/10000, 
                    name='基差', 
                    fill='tozeroy',
                    fillcolor='rgba(169, 169, 169, 0.2)',
                    line=dict(color='rgba(169, 169, 169, 0.5)', width=1),
                    yaxis='y2',
                    hovertemplate='<b>基差</b><br>时间: %{x}<br>基差: %{y:.2f}万<extra></extra>'
                ))
                
                # 计算基差平均线
                mean_basis = df['Basis'].mean() / 10000
                fig1.add_hline(y=mean_basis, line_dash="dot", 
                             line_color="gray", opacity=0.5,
                             annotation_text=f"平均基差: {mean_basis:.2f}万",
                             annotation_position="bottom right")
                
                fig1.update_layout(
                    title="价格与基差走势监控",
                    template="plotly_white",
                    height=500,
                    hovermode="x unified",
                    margin=dict(t=50, b=50, l=50, r=50),
                    legend=dict(
                        orientation="h",
                        yanchor="bottom",
                        y=1.02,
                        xanchor="right",
                        x=1
                    ),
                    xaxis=dict(
                        showgrid=True,
                        gridwidth=1,
                        gridcolor='rgba(128, 128, 128, 0.1)',
                        title="时间"
                    ),
                    yaxis=dict(
                        title="价格 (万元)",
                        showgrid=True,
                        gridwidth=1,
                        gridcolor='rgba(128, 128, 128, 0.1)'
                    ),
                    yaxis2=dict(
                        title="基差 (万元)",
                        overlaying='y',
                        side='right',
                        showgrid=False
                    ),
                    plot_bgcolor='white',
                    paper_bgcolor='white'
                )
                
                st.plotly_chart(fig1, use_container_width=True)

            with t2:
                # 对冲波动稳定性 - 现代设计
                fig2 = make_subplots(
                    rows=2, cols=1,
                    row_heights=[0.7, 0.3],
                    vertical_spacing=0.1,
                    subplot_titles=("套保前后价值变动对比", "套保效果差值"),
                    shared_xaxes=True
                )
                
                # 主要图表：价值变动
                fig2.add_trace(go.Scatter(
                    x=df['Date'], y=df['Value_Change_NoHedge']/10000, 
                    name='未套保',
                    line=dict(color='#FF6B6B', width=2, dash='dash'),
                    opacity=0.6,
                    hovertemplate='<b>未套保</b><br>时间: %{x}<br>价值变动: %{y:.2f}万<extra></extra>'
                ), row=1, col=1)
                
                fig2.add_trace(go.Scatter(
                    x=df['Date'], y=df['Value_Change_Hedged']/10000, 
                    name='套保后',
                    line=dict(color='#4ECDC4', width=3),
                    hovertemplate='<b>套保后</b><br>时间: %{x}<br>价值变动: %{y:.2f}万<extra></extra>'
                ), row=1, col=1)
                
                # 添加填充区域显示套保效果
                fig2.add_trace(go.Scatter(
                    x=df['Date'], 
                    y=df['Value_Change_Hedged']/10000,
                    mode='lines',
                    line=dict(width=0),
                    showlegend=False,
                    hoverinfo='skip'
                ), row=1, col=1)
                
                fig2.add_trace(go.Scatter(
                    x=df['Date'], 
                    y=df['Value_Change_NoHedge']/10000,
                    mode='lines',
                    line=dict(width=0),
                    fill='tonexty',
                    fillcolor='rgba(255, 107, 107, 0.2)',
                    showlegend=False,
                    hoverinfo='skip'
                ), row=1, col=1)
                
                # 底部图表：套保效果（差值）
                hedge_benefit = (df['Value_Change_Hedged'] - df['Value_Change_NoHedge'])/10000
                fig2.add_trace(go.Bar(
                    x=df['Date'], y=hedge_benefit,
                    name='套保效果',
                    marker_color=['#4ECDC4' if x > 0 else '#FF6B6B' for x in hedge_benefit],
                    opacity=0.7,
                    hovertemplate='<b>套保效果</b><br>时间: %{x}<br>效益: %{y:.2f}万<extra></extra>'
                ), row=2, col=1)
                
                # 添加零线
                fig2.add_hline(y=0, line_dash="dot", line_color="gray", opacity=0.5, row=2, col=1)
                
                fig2.update_layout(
                    template="plotly_white",
                    height=600,
                    hovermode="x unified",
                    showlegend=True,
                    legend=dict(
                        orientation="h",
                        yanchor="bottom",
                        y=1.02,
                        xanchor="right",
                        x=1
                    ),
                    plot_bgcolor='white',
                    paper_bgcolor='white'
                )
                
                fig2.update_xaxes(title_text="时间", row=2, col=1)
                fig2.update_yaxes(title_text="价值变动 (万元)", row=1, col=1)
                fig2.update_yaxes(title_text="套保效益 (万元)", row=2, col=1)
                
                st.plotly_chart(fig2, use_container_width=True)

            with t3:
                # 风险概率分布 - 美观的KDE密度图
                fig3 = go.Figure()
                
                # 准备数据
                nohedge_data = df['Cycle_PnL_NoHedge'].dropna()
                hedge_data = df['Cycle_PnL_Hedge'].dropna()
                
                if len(nohedge_data) > 1 and len(hedge_data) > 1:
                    # 创建KDE曲线
                    kde_nohedge = stats.gaussian_kde(nohedge_data)
                    kde_hedge = stats.gaussian_kde(hedge_data)
                    
                    # 创建X轴范围
                    x_min = min(nohedge_data.min(), hedge_data.min()) * 1.1
                    x_max = max(nohedge_data.max(), hedge_data.max()) * 1.1
                    x_range = np.linspace(x_min, x_max, 500)
                    
                    # 添加未套保KDE曲线
                    fig3.add_trace(go.Scatter(
                        x=x_range/10000, 
                        y=kde_nohedge(x_range),
                        name='未套保分布',
                        line=dict(color='#FF6B6B', width=3),
                        fill='tozeroy',
                        fillcolor='rgba(255, 107, 107, 0.3)',
                        hovertemplate='<b>未套保</b><br>盈亏: %{x:.2f}万<br>概率密度: %{y:.4f}<extra></extra>'
                    ))
                    
                    # 添加套保后KDE曲线
                    fig3.add_trace(go.Scatter(
                        x=x_range/10000, 
                        y=kde_hedge(x_range),
                        name='套保后分布',
                        line=dict(color='#4ECDC4', width=3),
                        fill='tozeroy',
                        fillcolor='rgba(78, 205, 196, 0.3)',
                        hovertemplate='<b>套保后</b><br>盈亏: %{x:.2f}万<br>概率密度: %{y:.4f}<extra></extra>'
                    ))
                    
                    # 计算统计指标
                    stats_nohedge = {
                        'mean': nohedge_data.mean()/10000,
                        'std': nohedge_data.std()/10000,
                        'median': nohedge_data.median()/10000,
                        'q5': np.percentile(nohedge_data, 5)/10000,
                        'q95': np.percentile(nohedge_data, 95)/10000
                    }
                    
                    stats_hedge = {
                        'mean': hedge_data.mean()/10000,
                        'std': hedge_data.std()/10000,
                        'median': hedge_data.median()/10000,
                        'q5': np.percentile(hedge_data, 5)/10000,
                        'q95': np.percentile(hedge_data, 95)/10000
                    }
                    
                    # 添加统计标记
                    colors = {'nohedge': '#FF6B6B', 'hedge': '#4ECDC4'}
                    
                    # 添加均值线
                    fig3.add_vline(x=stats_nohedge['mean'], line_dash="dash", 
                                 line_color=colors['nohedge'], opacity=0.8,
                                 annotation_text=f"未套保均值: {stats_nohedge['mean']:.2f}万",
                                 annotation_position="top right")
                    
                    fig3.add_vline(x=stats_hedge['mean'], line_dash="dash", 
                                 line_color=colors['hedge'], opacity=0.8,
                                 annotation_text=f"套保后均值: {stats_hedge['mean']:.2f}万",
                                 annotation_position="top left")
                    
                    # 添加分位数标记
                    fig3.add_vrect(x0=stats_nohedge['q5'], x1=stats_nohedge['q95'],
                                 fillcolor=colors['nohedge'], opacity=0.1, line_width=0,
                                 annotation_text="未套保90%区间", annotation_position="top")
                    
                    fig3.add_vrect(x0=stats_hedge['q5'], x1=stats_hedge['q95'],
                                 fillcolor=colors['hedge'], opacity=0.1, line_width=0,
                                 annotation_text="套保后90%区间", annotation_position="bottom")
                    
                    # 添加盈亏平衡线
                    fig3.add_vline(x=0, line_dash="dot", line_color="gray", opacity=0.7,
                                 annotation_text="盈亏平衡点", annotation_position="bottom")
                    
                    # 添加统计摘要框
                    fig3.add_annotation(
                        x=0.02, y=0.98,
                        xref="paper", yref="paper",
                        text=(
                            f"<b>统计摘要</b><br>"
                            f"<span style='color:{colors['nohedge']}'>未套保:</span> "
                            f"μ={stats_nohedge['mean']:.2f}万, σ={stats_nohedge['std']:.2f}万<br>"
                            f"<span style='color:{colors['hedge']}'>套保后:</span> "
                            f"μ={stats_hedge['mean']:.2f}万, σ={stats_hedge['std']:.2f}万<br>"
                            f"波动降低: <b>{(1-stats_hedge['std']/stats_nohedge['std'])*100:.1f}%</b>"
                        ),
                        showarrow=False,
                        align="left",
                        bordercolor="black",
                        borderwidth=1,
                        borderpad=4,
                        bgcolor="white",
                        opacity=0.9,
                        font=dict(size=11)
                    )
                
                fig3.update_layout(
                    title="风险概率密度分布 (KDE)",
                    template="plotly_white",
                    height=500,
                    xaxis_title="盈亏金额 (万元)",
                    yaxis_title="概率密度",
                    hovermode="x",
                    showlegend=True,
                    legend=dict(
                        orientation="h",
                        yanchor="bottom",
                        y=1.02,
                        xanchor="right",
                        x=1
                    ),
                    plot_bgcolor='white',
                    paper_bgcolor='white',
                    margin=dict(t=50, b=50, l=50, r=50)
                )
                
                st.plotly_chart(fig3, use_container_width=True)

            with t4:
                # 资金通道监管 - 现代设计
                fig4 = go.Figure()
                
                # 添加区域背景
                fig4.add_trace(go.Scatter(
                    x=df['Date'], 
                    y=df['Line_Withdraw']/10000, 
                    name='提盈警戒线', 
                    line=dict(color='rgba(76, 175, 80, 0.5)', width=2, dash='dash'),
                    hovertemplate='<b>提盈线</b><br>时间: %{x}<br>金额: %{y:.2f}万<extra></extra>'
                ))
                
                fig4.add_trace(go.Scatter(
                    x=df['Date'], 
                    y=df['Line_Inject']/10000, 
                    name='补金警戒线', 
                    line=dict(color='rgba(244, 67, 54, 0.5)', width=2, dash='dash'),
                    fill='tonexty',
                    fillcolor='rgba(255, 235, 59, 0.2)',
                    hovertemplate='<b>补金线</b><br>时间: %{x}<br>金额: %{y:.2f}万<extra></extra>'
                ))
                
                # 添加账户权益线
                fig4.add_trace(go.Scatter(
                    x=df['Date'], 
                    y=df['Account_Equity']/10000, 
                    name='账户权益', 
                    line=dict(color='#2E86AB', width=4),
                    hovertemplate='<b>账户权益</b><br>时间: %{x}<br>权益: %{y:.2f}万<extra></extra>'
                ))
                
                # 添加保证金要求线
                fig4.add_trace(go.Scatter(
                    x=df['Date'], 
                    y=df['Margin_Required']/10000, 
                    name='保证金要求', 
                    line=dict(color='#F24236', width=2, dash='dot'),
                    opacity=0.7,
                    hovertemplate='<b>保证金要求</b><br>时间: %{x}<br>金额: %{y:.2f}万<extra></extra>'
                ))
                
                # 添加补金点（更美观的标记）
                if not inj_events.empty:
                    fig4.add_trace(go.Scatter(
                        x=inj_events['Date'], 
                        y=inj_events['Account_Equity']/10000,
                        mode='markers+text',
                        name='补金事件',
                        marker=dict(
                            color='#F24236',
                            symbol='triangle-up',
                            size=16,
                            line=dict(color='white', width=2)
                        ),
                        text=[f"+{amt/10000:.1f}" for amt in inj_events['Cash_Injection']],
                        textposition="top center",
                        textfont=dict(color='#F24236', size=10, family='Arial Black'),
                        hovertemplate='<b>补金事件</b><br>时间: %{x}<br>权益: %{y:.1f}万<br>补金: +%{text}万<extra></extra>'
                    ))
                
                # 添加提盈点（更美观的标记）
                if not wit_events.empty:
                    fig4.add_trace(go.Scatter(
                        x=wit_events['Date'], 
                        y=wit_events['Account_Equity']/10000,
                        mode='markers+text',
                        name='提盈事件',
                        marker=dict(
                            color='#4CAF50',
                            symbol='triangle-down',
                            size=16,
                            line=dict(color='white', width=2)
                        ),
                        text=[f"-{amt/10000:.1f}" for amt in wit_events['Cash_Withdrawal']],
                        textposition="bottom center",
                        textfont=dict(color='#4CAF50', size=10, family='Arial Black'),
                        hovertemplate='<b>提盈事件</b><br>时间: %{x}<br>权益: %{y:.1f}万<br>提盈: -%{text}万<extra></extra>'
                    ))
                
                # 添加资金调度统计
                total_injections = inj_events['Cash_Injection'].sum()/10000
                total_withdrawals = wit_events['Cash_Withdrawal'].sum()/10000
                
                fig4.add_annotation(
                    x=0.98, y=0.02,
                    xref="paper", yref="paper",
                    text=(
                        f"<b>资金调度统计</b><br>"
                        f"补金次数: <span style='color:#F24236'>{len(inj_events)}次</span><br>"
                        f"提盈次数: <span style='color:#4CAF50'>{len(wit_events)}次</span><br>"
                        f"净流出: <b>{(total_withdrawals-total_injections):.1f}万</b>"
                    ),
                    showarrow=False,
                    align="right",
                    bordercolor="gray",
                    borderwidth=1,
                    borderpad=6,
                    bgcolor="white",
                    opacity=0.9,
                    font=dict(size=11)
                )
                
                fig4.update_layout(
                    title="资金通道监管 - 账户权益与资金调度",
                    template="plotly_white",
                    height=500,
                    hovermode="x unified",
                    yaxis=dict(title="金额 (万元)"),
                    xaxis=dict(title="时间"),
                    showlegend=True,
                    legend=dict(
                        orientation="h",
                        yanchor="bottom",
                        y=1.02,
                        xanchor="right",
                        x=1
                    ),
                    plot_bgcolor='white',
                    paper_bgcolor='white',
                    margin=dict(t=50, b=50, l=50, r=50)
                )
                
                st.plotly_chart(fig4, use_container_width=True)
                
                # 资金调度详情表格（现代化设计）
                if not inj_events.empty or not wit_events.empty:
                    st.subheader("📋 资金调度明细")
                    
                    # 创建数据表格
                    event_data = []
                    
                    for idx, row in inj_events.iterrows():
                        event_data.append({
                            '时间': row['Date'],
                            '类型': '🔴 补金',
                            '金额(万)': f"+{row['Cash_Injection']/10000:.2f}",
                            '账户权益(万)': f"{row['Account_Equity']/10000:.2f}",
                            '触发原因': '账户权益低于补金警戒线'
                        })
                    
                    for idx, row in wit_events.iterrows():
                        event_data.append({
                            '时间': row['Date'],
                            '类型': '🟢 提盈',
                            '金额(万)': f"-{row['Cash_Withdrawal']/10000:.2f}",
                            '账户权益(万)': f"{row['Account_Equity']/10000:.2f}",
                            '触发原因': '账户权益高于提盈触发线'
                        })
                    
                    if event_data:
                        event_df = pd.DataFrame(event_data).sort_values('时间', ascending=False)
                        
                        # 使用st.dataframe的样式功能
                        st.dataframe(
                            event_df,
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                '时间': st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
                                '类型': st.column_config.TextColumn(width="small"),
                                '金额(万)': st.column_config.TextColumn(width="small"),
                                '账户权益(万)': st.column_config.NumberColumn(format="%.2f"),
                                '触发原因': st.column_config.TextColumn(width="medium")
                            }
                        )

            # --- 原版摘要分析文本 ---
            st.markdown("---")
            st.subheader("📝 稳定性分析结论")
            
            # 使用卡片式布局
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("""
                <div style="background: linear-gradient(135deg, #E3F2FD 0%, #BBDEFB 100%); 
                            border-radius: 10px; padding: 20px; margin-bottom: 20px; 
                            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);">
                    <h4 style="color: #1565C0; margin-top: 0;">✅ 风险对冲质量</h4>
                    <p>通过套期保值策略，资产净值的波动幅度被压制在了现货波动的 <b>{:.1f}%</b> 范围内，风险控制效果显著。</p>
                    
                    <h4 style="color: #1565C0;">✅ 极端生存能力</h4>
                    <p>在回测期内最不利的价格波动下，套保方案成功挽救了约 <b>{:.2f} 万元</b> 的潜在损失，增强了企业的抗风险能力。</p>
                </div>
                """.format(100-stability_boost, loss_saved), unsafe_allow_html=True)
            
            with col2:
                st.markdown("""
                <div style="background: linear-gradient(135deg, #E8F5E9 0%, #C8E6C9 100%); 
                            border-radius: 10px; padding: 20px; margin-bottom: 20px; 
                            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);">
                    <h4 style="color: #2E7D32; margin-top: 0;">✅ 资金运营效率</h4>
                    <p>系统平均每 <b>{:.1f}</b> 天触发一次资金调度，操作频率合理，资金使用效率良好。</p>
                    
                    <h4 style="color: #2E7D32;">✅ 收益确定性增强</h4>
                    <p>套保后的盈亏分布明显向中心靠拢，大幅降低了企业经营的'意外'风险，提升了收益的确定性。</p>
                </div>
                """.format(len(df)/(len(inj_events)+len(wit_events)+1)), unsafe_allow_html=True)

            # 下载按钮美化
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='回测数据')
                if 'event_df' in locals():
                    event_df.to_excel(writer, index=False, sheet_name='资金调度明细')
            
            st.markdown("""
            <style>
            .stDownloadButton button {
                background: linear-gradient(135deg, #4CAF50 0%, #2E7D32 100%);
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
                transition: all 0.3s ease;
            }
            .stDownloadButton button:hover {
                transform: translateY(-2px);
                box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
            }
            </style>
            """, unsafe_allow_html=True)
            
            st.download_button(
                "📥 下载完整回测数据报告",
                data=output.getvalue(),
                file_name='套期保值回测报告.xlsx',
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
else:
    st.info("👆 请上传 CSV 数据文件开启系统分析。")











