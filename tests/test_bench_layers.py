import httpx
import pytest

from bench.bench_layers import time_http


@pytest.mark.parametrize("status", [404, 500])
def test_http_benchmark_sends_unknown_cancels_and_checks_status(status):
    requests = []

    def respond(request):
        requests.append((request.method, request.url.path))
        if request.method == "DELETE":
            return httpx.Response(status)
        return httpx.Response(200, json={"total_orders_submitted": 0, "total_trades_executed": 0})

    with httpx.Client(base_url="http://benchmark", transport=httpx.MockTransport(respond)) as client:
        if status == 404:
            assert time_http(client, ["O1"], [False])["ops_per_sec"] > 0
            assert requests == [("DELETE", "/orders/BENCH/missing-O1"), ("GET", "/stats/detailed")]
        else:
            with pytest.raises(RuntimeError, match="returned 500, expected 404"):
                time_http(client, ["O1"], [False])
