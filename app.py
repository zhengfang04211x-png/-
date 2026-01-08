import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from scipy.stats import gaussian_kde
import io

# 1. 页面配置
st.set_page_config(page_title="套期保值回测", layout="wide", initial_sidebar_state="expanded")

# 2. 样式
st.markdown("""<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;}</style>""", unsafe_allow_html=True)

# 3. 侧边栏
st.sidebar.header("🛠️ 参数配置")
uploaded_file = st.sidebar.file_uploader("上传 CSV", type=['csv'])
multiplier = st.sidebar.number_input("合约乘数", value=10)
lots = st.sidebar.number_input("手数", value=3)
hedge_ratio = st.sidebar.slider("套保比例", 0.0, 1.2, 1.0)
margin_rate = st.sidebar.number_input("保证金率", value=0.12)
inject_ratio = st.sidebar.number_input("补金警戒线", value=1.2)
withdraw_ratio = st.sidebar.number_input("提盈触发线", value=1.5)
holding_days = st.sidebar.slider("周期 (天)", 7, 90, 30)

# 4. 计算逻辑 (加固数据清洗)
@st.cache_data
def process_data(df_input, q, ratio, m_rate, inject_r, withdraw_r, days):
    df = df_input.copy()
    for col in ['Spot', 'Futures']:
        if df[col].dtype == 'object':
            df[col] = df[col].astype(str).str.replace(',', '').str.strip()
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.ffill().bfill() 

    df['Cycle_PnL_NoHedge'] = df['Spot'].diff(days) * q
    df['Cycle_PnL_Hedge'] = (df['Spot'].diff(days) * q) - (df['Futures'].diff(days) * q * ratio)

    equity_list, margin_req_list, cash_in_list, cash_out_list = [], [], [], []
    current_equity = df['Futures'].iloc[0] * q * ratio * m_rate * inject_r

    for i in range(len(df)):
        price = df['Futures'].iloc[i]
        if i > 0: current_equity += -(price - df['Futures'].iloc[i-1]) * q * ratio
        req_margin = price * q * ratio * m_rate
        margin_req_list.append(req_margin)
        
        in_amt, out_amt = 0, 0
        if current_equity < req_margin * inject_r:
            in_amt = req_margin * inject_r - current_equity
            current_equity += in_amt
        elif current_equity > req_margin * withdraw_r:
            out_amt = current_equity - req_margin * withdraw_r
            current_equity -= out_amt
        cash_in_list.append(in_amt); cash_out_list.append(out_amt); equity_list.append(current_equity)

    df['Account_Equity'] = equity_list
    df['Cash_Injection'], df['Cash_Withdrawal'] = cash_in_list, cash_out_list
    df['Line_Inject'] = np.array(margin_req_list) * inject_r
    df['Line_Withdraw'] = np.array(margin_req_list) * withdraw_r
    
    cum_cash = pd.Series(cash_out_list).cumsum() - pd.Series(cash_in_list).cumsum()
    df['Value_Change_NoHedge'] = (df['Spot'] - df['Spot'].iloc[0]) * q
    df['Value_Change_Hedged'] = (df['Spot'] * q) + df['Account_Equity'] + cum_cash - ((df['Spot'].iloc[0] * q) + (df['Futures'].iloc[0] * q * ratio * m_rate * inject_r))
    return df

# 5. 绘图
if uploaded_file:
    try: raw_df = pd.read_csv(uploaded_file, encoding='gbk')
    except: raw_df = pd.read_csv(uploaded_file, encoding='utf-8-sig')
    
    col_time = next(c for c in raw_df.columns if any(k in c for k in ['时间', 'Date']))
    col_spot = next(c for c in raw_df.columns if '现货' in c)
    col_fut = next(c for c in raw_df.columns if any(k in c for k in ['期货', '价格']))
    raw_df = raw_df.rename(columns={col_time: 'Date', col_spot: 'Spot', col_fut: 'Futures'})
    raw_df['Date'] = pd.to_datetime(raw_df['Date'])
    
    df = process_data(raw_df, lots*multiplier, hedge_ratio, margin_rate, inject_ratio, withdraw_ratio, holding_days)

    t1, t2, t3, t4 = st.tabs(["📉 价格基差", "🛡️ 对冲波动", "📊 风险分布", "🏦 资金监控"])
    H = 800 

    with t1:
        fig1 = go.Figure()
        fig1.add_trace(go.Scatter(x=df['Date'], y=df['Spot'], name='现货'))
        fig1.add_trace(go.Scatter(x=df['Date'], y=df['Futures'], name='期货'))
        fig1.update_layout(height=H, hovermode="x unified")
        st.plotly_chart(fig1, use_container_width=True)

    with t2:
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=df['Date'], y=df['Value_Change_NoHedge'], name='未套保', line=dict(color='red', width=1), opacity=0.4))
        fig2.add_trace(go.Scatter(x=df['Date'], y=df['Value_Change_Hedged'], name='已套保', line=dict(color='green', width=3)))
        fig2.update_layout(height=H, hovermode="x unified")
        st.plotly_chart(fig2, use_container_width=True)

    with t3:
        # 🛡️ 弃用 create_distplot，手动构建 KDE 曲线，彻底防崩
        fig3 = go.Figure()
        colors = {'未套保': 'red', '已套保': 'green'}
        for label, col_name in zip(['未套保', '已套保'], ['Cycle_PnL_NoHedge', 'Cycle_PnL_Hedge']):
            data = df[col_name].dropna()
            data = data[np.isfinite(data)] # 剔除无穷大
            if len(data) > 1:
                # 画直方图
                fig3.add_trace(go.Histogram(x=data, name=f'{label}分布', histnorm='probability density', 
                                          marker_color=colors[label], opacity=0.3))
                # 画KDE曲线
                kde = gaussian_kde(data)
                x_range = np.linspace(data.min(), data.max(), 200)
                fig3.add_trace(go.Scatter(x=x_range, y=kde(x_range), name=f'{label}曲线', 
                                        line=dict(color=colors[label], width=2)))
        fig3.update_layout(height=H, barmode='overlay', title="风险盈亏分布 (KDE 稳健版)", xaxis_title="盈亏金额")
        st.plotly_chart(fig3, use_container_width=True)
        

    with t4:
        fig4 = go.Figure()
        fig4.add_trace(go.Scatter(x=df['Date'], y=df['Account_Equity'], name='期货权益', line=dict(color='black', width=2)))
        fig4.add_trace(go.Scatter(x=df['Date'], y=df['Line_Inject'], name='补金线', line=dict(dash='dot', color='red')))
        fig4.add_trace(go.Scatter(x=df['Date'], y=df['Line_Withdraw'], name='提盈线', line=dict(dash='dot', color='blue')))
        inj = df[df['Cash_Injection'] > 0]
        fig4.add_trace(go.Scatter(x=inj['Date'], y=inj['Account_Equity'], mode='markers', name='补仓点', 
                                marker=dict(color='red', symbol='triangle-up', size=15)))
        fig4.update_layout(height=H, hovermode="x unified")
        st.plotly_chart(fig4, use_container_width=True)

    st.success("图表已放大，KDE 分布图已切换为稳健模式，不再报错。")
else:
    st.info("上传 CSV 后开始。")







