from pathlib import Path


def test_index_does_not_depend_on_external_cdn_assets():
    html = Path("app/static/index.html").read_text(encoding="utf-8")

    assert "https://unpkg.com" not in html
    assert "https://cdn.jsdelivr.net" not in html


def test_frontend_uses_real_map_and_compact_wind_barb_markers():
    html = Path("app/static/index.html").read_text(encoding="utf-8")
    script = Path("app/static/app.js").read_text(encoding="utf-8")
    styles = Path("app/static/styles.css").read_text(encoding="utf-8")

    assert "/static/vendor/leaflet/leaflet.js" in html
    assert 'id="leafletMap"' in html
    assert "L.map" in script
    assert "fitStationsOnMap" in script
    assert "renderWindBarb" in script
    assert "windBarbRotation" in script
    assert "width: 34px" in styles
    assert "平均風速" in script


def test_offline_page_prefers_live_local_api_before_snapshot_fallback():
    script = Path("app/static/app.js").read_text(encoding="utf-8")

    assert "LIVE_API_BASE" in script
    assert "getLiveJson" in script
    assert "/api/refresh" in script
    assert "async function refreshPageData()" in script
    assert "await triggerRefresh();\n    await refreshPageData();" in script
    assert "async function refreshPageData() {\n  await triggerRefresh();" not in script
    assert "getOfflineJson(url)" in script
    assert script.index("getLiveJson") < script.index("getOfflineJson(url)")


def test_homepage_embeds_windy_macau_weather_map():
    html = Path("app/static/index.html").read_text(encoding="utf-8")
    styles = Path("app/static/styles.css").read_text(encoding="utf-8")

    assert 'id="windy"' in html
    assert "embed.windy.com" in html
    assert "lat=22.17" in html
    assert "lon=113.55" in html
    assert "zoom=8" in html
    assert "overlay=wind" in html
    assert ".windy-frame" in styles
    assert "height: clamp(560px, 72vh, 820px)" in styles


def test_homepage_contains_puiching_style_weather_modules():
    html = Path("app/static/index.html").read_text(encoding="utf-8")
    script = Path("app/static/app.js").read_text(encoding="utf-8")

    for section_id in ("alerts", "wind", "water", "air", "database", "officialForecast"):
        assert f'id="{section_id}"' in html

    assert "/api/dashboard" in script
    assert "/api/export/weather.csv" in script
    assert "renderDashboardModules" in script
    assert "renderOfficialForecast" in script
    assert "forecast-tile" in script
    assert "safeText" in script
    assert "windIndexPanel" in html
    assert "airQualityPanel" in html


def test_offline_export_inlines_leaflet_assets(tmp_path):
    from app.export_static import build_offline_html

    output = build_offline_html(db_path=tmp_path / "weather.sqlite", output=tmp_path / "offline.html")
    html = output.read_text(encoding="utf-8")

    assert "/static/vendor/leaflet/leaflet.js" not in html
    assert "L.map" in html
    assert "window.OFFLINE_DATA" in html
    assert "20260524-chart2" not in html


def test_offline_export_includes_cached_official_forecast(tmp_path):
    from app.db import WeatherDatabase
    from app.export_static import build_offline_html

    db_path = tmp_path / "weather.sqlite"
    db = WeatherDatabase(db_path)
    db.init()
    db.upsert_external_cache(
        "official_forecast",
        "https://xml.smg.gov.mo/c_7daysforecast.xml",
        "active",
        {
            "status": "active",
            "items": [
                {
                    "valid_for": "2026-05-24",
                    "description": "多雲，有驟雨。",
                    "temp_high": 31,
                    "temp_low": 27,
                }
            ],
        },
    )

    output = build_offline_html(db_path=db_path, output=tmp_path / "offline.html")
    html = output.read_text(encoding="utf-8")

    assert '"official_forecast": {"status": "active"' in html
    assert '"valid_for": "2026-05-24"' in html
    assert '"temp_high": 31' in html


def test_chart_visualization_has_monitoring_quality_features():
    html = Path("app/static/index.html").read_text(encoding="utf-8")
    script = Path("app/static/app.js").read_text(encoding="utf-8")
    chart = Path("app/static/chart-lite.js").read_text(encoding="utf-8")

    assert "historyChartStats" in html
    assert "chartStats" in script
    assert "renderHistoryStats" in script
    assert "niceDomain" in chart
    assert "_drawMeanLine" in chart
    assert "_drawExtremes" in chart
    assert "_drawHover" in chart
    assert "_drawPlotBackground" in chart


def test_static_assets_are_cache_busted_for_chart_update():
    html = Path("app/static/index.html").read_text(encoding="utf-8")

    assert "/static/chart-lite.js?v=20260524-overview1" in html
    assert "/static/app.js?v=20260524-overview1" in html
    assert "/static/styles.css?v=20260524-overview1" in html


def test_monitoring_overview_metric_matrix_and_group_controls_exist():
    html = Path("app/static/index.html").read_text(encoding="utf-8")
    script = Path("app/static/app.js").read_text(encoding="utf-8")

    assert "overview-status" in html
    assert "metric-matrix" in html
    assert "data-metric=\"rainfall_hour\"" in html
    assert "groupPresets" in html
    assert "historyInterval" in html
    assert "historyExportLink" in html
    assert "qualityPanel" in html
    assert "warningEventList" in html
    assert "initMetricMatrix" in script
    assert "initGroupPresets" in script
    assert "renderDataQuality" in script
    assert "/api/data-quality" in script
    assert "/api/warning-events" in script
    assert "/api/export/history.csv" in script
