#!/bin/bash
# Token diambil dari env var - jangan hardcode!
TOKEN=${VERCEL_TOKEN:-""}
ALIAS="infinitysenderblast.vercel.app"

if [ -z "$TOKEN" ]; then
  echo "❌ Set VERCEL_TOKEN dulu: export VERCEL_TOKEN=xxx"
  exit 1
fi

echo "🚀 Deploying..."
DEPLOY_URL=$(npx vercel --prod --force --yes --token $TOKEN 2>&1 | grep "Production:" | head -1 | awk '{print $2}')
echo "✅ Deployed: $DEPLOY_URL"

echo "🔗 Setting alias..."
npx vercel alias $DEPLOY_URL $ALIAS --token $TOKEN
echo "✅ Alias set: https://$ALIAS"
