from typing import Dict, List, Optional, Tuple

import networkx as nx
from pyvis.network import Network

from src.analysis.propagator import KeywordPropagator
from src.models import ChannelNode


class CommunityDetector:
    """Build channel similarity network and detect niche communities.

    Uses KeywordPropagator results to build a channel-level graph where:
    - Nodes = channels
    - Edges = cosine similarity between channel keyword vectors
    - Communities = Louvain clusters
    """

    def __init__(self, propagator: KeywordPropagator):
        self.propagator = propagator

    def build_channel_graph(
        self,
        similarities: Dict[Tuple[str, str], float],
    ) -> nx.Graph:
        """Build a NetworkX graph from propagator similarity results."""
        G = nx.Graph()
        for (ch_a, ch_b), sim in similarities.items():
            G.add_node(ch_a)
            G.add_node(ch_b)
            G.add_edge(ch_a, ch_b, weight=sim)
        return G

    def detect_communities(self, G: nx.Graph) -> Dict[str, int]:
        """Run Louvain community detection on the channel graph.

        Returns: dict of channel_name -> community_id
        """
        if G.number_of_edges() == 0:
            return {node: 0 for node in G.nodes()}

        from networkx.algorithms.community import louvain_communities

        communities = louvain_communities(G, seed=42)
        result: Dict[str, int] = {}
        for cid, community in enumerate(communities):
            for node in community:
                result[node] = cid
        return result

    def export_network(
        self,
        G: nx.Graph,
        communities: Dict[str, int],
        channel_keywords: Dict[str, Dict[str, float]],
        propagated: Dict[str, Dict[str, float]],
        channel_data: Optional[Dict[str, Dict]] = None,
        output_path: str = "output/graph.html",
    ) -> str:
        """Generate interactive Pyvis network graph with channels as nodes.

        Node size = channel total views (from channel_data)
        Node color = community (from community detection)
        Hover tooltip = top-5 keywords + 4 metrics
        """
        net = Network(height="700px", width="100%", bgcolor="#ffffff")

        # Color palette for communities
        colors = [
            "#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4", "#FFEAA7",
            "#DDA0DD", "#98D8C8", "#F7DC6F", "#BB8FCE", "#85C1E9",
        ]

        if channel_data is None:
            channel_data = {}

        for channel in G.nodes():
            cid = communities.get(channel, 0)
            data = channel_data.get(channel, {})

            # Get top-5 keywords for this channel
            top5 = self.propagator.rank_keywords(propagated, channel, top_n=5)
            kw_list = "<br>".join(
                f"  {kw}: {score:.2f}" for kw, score in top5
            ) if top5 else "  (none)"

            total_views = data.get("total_views", 0)
            size = max(10, min(80, total_views / 10_000))

            net.add_node(
                channel,
                label=channel,
                title=(
                    f"<b>{channel}</b><br><br>"
                    f"<b>Top Keywords:</b><br>{kw_list}<br><br>"
                    f"Total Views: {total_views:,}<br>"
                    f"Videos: {data.get('video_count', 0)}<br>"
                    f"Opportunity Score: {data.get('opportunity_score', 0):.2f}<br>"
                    f"Supply Growth: {data.get('supply_growth', 0):.4f}<br>"
                    f"Demand Growth: {data.get('demand_growth', 0):.4f}"
                ),
                size=size,
                color=colors[cid % len(colors)],
            )

        for ch_a, ch_b, edge_data in G.edges(data=True):
            sim = edge_data.get("weight", 0)
            net.add_edge(ch_a, ch_b, weight=sim, title=f"Similarity: {sim:.3f}")

        net.set_options("""
        {
          "physics": {
            "stabilization": {"iterations": 100},
            "barnesHut": {"gravitationalConstant": -3000, "springLength": 200}
          },
          "interaction": {
            "hover": true,
            "tooltipDelay": 100,
            "dragNodes": true,
            "zoomView": true
          }
        }
        """)

        net.save_graph(output_path)
        return output_path
