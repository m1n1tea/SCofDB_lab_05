-- wrk script: GET catalog cache endpoint
-- Usage:
-- wrk -t4 -c100 -d30s -s loadtest/wrk/catalog.lua http://localhost:8082

wrk.method = "GET"
wrk.path = "/api/cache-demo/catalog?use_cache=false"
