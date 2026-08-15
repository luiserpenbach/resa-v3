"""Shared Plotly styling for Studio HTML artifacts (dark, no chrome titles)."""
from __future__ import annotations

STUDIO_HTML_CONFIG = {"displaylogo": False, "responsive": True}


def apply_studio_theme(fig, title: str = ""):
    """Dark template, transparent-enough paper, autosize for iframe fill."""
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0f1014",
        plot_bgcolor="#0f1014",
        font=dict(family="system-ui, sans-serif", color="#c8cdd3", size=12),
        title=dict(
            text=title,
            font=dict(size=13, color="#e6e8eb"),
            x=0.01,
            xanchor="left",
        ) if title else None,
        margin=dict(l=56, r=36, t=44 if title else 28, b=52),
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    bgcolor="rgba(0,0,0,0)", font=dict(size=11)),
        autosize=True,
    )
    fig.layout.width = None
    fig.layout.height = None
    return fig


def write_studio_html(fig, path) -> None:
    fig.write_html(str(path), include_plotlyjs="cdn",
                   config=STUDIO_HTML_CONFIG, full_html=True)
