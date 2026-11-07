import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

def plot_distance_distribution(exact_df: pd.DataFrame, estimated_df: pd.DataFrame, sample_rate: float) -> go.Figure:
    """
    O5: Generează un grafic Plotly care compară distribuția exactă a distanțelor
    cu cea estimată dintr-un eșantion.
    """
    exact_df = exact_df.copy()
    estimated_df = estimated_df.copy()
    
    exact_df["Type"] = "Exact (100%)"
    estimated_df["Type"] = f"Estimated ({int(sample_rate*100)}%)"
    
    plot_data = pd.concat([exact_df, estimated_df])
    plot_data.rename(columns={"group_key": "Distance Bin", "value": "Trip Count"}, inplace=True)
    
    fig = px.bar(
        plot_data,
        x="Distance Bin",
        y="Trip Count",
        color="Type",
        barmode="group",
        title=f"Distribuția Distanțelor: Exact vs Eșantion ({int(sample_rate*100)}%)",
        labels={"Distance Bin": "Interval Distanță (Bin)", "Trip Count": "Număr Estimat de Curse"}
    )
    
    fig.update_layout(
        xaxis_title="Interval Distanță",
        yaxis_title="Număr Curse",
        legend_title="Metodă",
        template="plotly_white"
    )
    
    return fig