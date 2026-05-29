#!/bin/bash
# Usage: bash scripts/run-and-deploy.sh keyword1 "keyword 2" keyword3 ...
# Example: bash scripts/run-and-deploy.sh "Minecraft meme" "minecraft funny" "minecraft grox"

set -e
cd "$(dirname "$0")/.."

echo "=== Step 1: Run pipeline ==="
rm -rf output
mkdir -p output
python src/cli.py "$@" -o output

echo ""
echo "=== Step 2: Copy output to repo root ==="
cp output/niche_wordcloud.html output/graph_7plus7.html output/cluster_report.json .

echo ""
echo "=== Step 3: Commit and push ==="
git add niche_wordcloud.html graph_7plus7.html cluster_report.json src/ .env.example server.py dashboard.html scripts/
git commit -m "feat: run with $*"
git push

echo ""
echo "=== Done! ==="
echo "Web: https://eforerik7687-ctrl.github.io/YouTube-Niche-Discovery-Algorithm/dashboard.html"
echo "Analytics: https://spraysword.goatcounter.com"
