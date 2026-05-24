from pathlib import Path

from app.smg import parse_actual_weather, parse_air_quality_forecast, parse_seven_day_forecast, parse_warning_xml


def test_parse_actual_weather_extracts_station_metrics_and_rainfall_types():
    xml_bytes = Path("tests/fixtures/sample_actualweather.xml").read_bytes()

    readings = parse_actual_weather(xml_bytes)

    assert len(readings) == 2
    tg = readings[0]
    assert tg.station_code == "TG"
    assert tg.station_name == "大潭山"
    assert tg.record_time.isoformat() == "2026-05-23T14:15:00"
    assert tg.temperature == 28.2
    assert tg.humidity == 88
    assert tg.dew_point == 26.0
    assert tg.wind_gust == 26.6
    assert tg.wind_speed == 13.3
    assert tg.rainfall_current == 0.0
    assert tg.rainfall_hour == 1.2
    assert tg.rainfall_day == 8.4
    assert tg.wind_direction == "S"
    assert tg.wind_degree == 175
    assert tg.mean_sea_level_pressure == 1008.9


def test_parse_actual_weather_allows_wind_only_stations():
    xml_bytes = Path("tests/fixtures/sample_actualweather.xml").read_bytes()

    readings = parse_actual_weather(xml_bytes)

    mn = readings[1]
    assert mn.station_code == "MN"
    assert mn.temperature is None
    assert mn.wind_speed == 25.2
    assert mn.wind_direction == "SSW"


def test_parse_seven_day_forecast_extracts_daily_ranges():
    xml = """
    <SevenDaysForecast>
      <System><SysPubdate>2026-05-23 17:00</SysPubdate></System>
      <Custom>
        <WeatherForecast>
          <ValidFor>2026-05-24</ValidFor>
          <c_DayOfWeek>日</c_DayOfWeek>
          <Icon><IconURL>https://example.test/weather.gif</IconURL></Icon>
          <WeatherStatus>02</WeatherStatus>
          <Temperature><Type>1</Type><Value>31</Value></Temperature>
          <Temperature><Type>2</Type><Value>27</Value></Temperature>
          <Humidity><Type>1</Type><Value>95</Value></Humidity>
          <Humidity><Type>2</Type><Value>70</Value></Humidity>
          <WeatherDescription>多雲，有驟雨。</WeatherDescription>
        </WeatherForecast>
      </Custom>
    </SevenDaysForecast>
    """.encode()

    forecast = parse_seven_day_forecast(xml)

    assert forecast["status"] == "active"
    assert forecast["updated_at"] == "2026-05-23 17:00"
    assert forecast["items"][0]["temp_high"] == 31
    assert forecast["items"][0]["temp_low"] == 27
    assert forecast["items"][0]["description"] == "多雲，有驟雨。"


def test_parse_air_quality_forecast_extracts_station_reports():
    xml = """
    <ForecastIQA>
      <System><SysPubdate>2026-05-23 17:30:26</SysPubdate></System>
      <Custom>
        <ReportDescription>預測今晚至明日空氣質量水平</ReportDescription>
        <AQIForecastReport>
          <Station code="BDR">
            <Stationname>路邊</Stationname>
            <AQIForecast>
              <ValidFor>2026-05-24</ValidFor>
              <Value>30-50</Value>
              <AQIForecastDescription>良好</AQIForecastDescription>
            </AQIForecast>
          </Station>
        </AQIForecastReport>
        <Complementary>
          <Level>良好</Level>
          <GeneralPublic>可如常活動。</GeneralPublic>
        </Complementary>
      </Custom>
    </ForecastIQA>
    """.encode()

    air = parse_air_quality_forecast(xml)

    assert air["status"] == "active"
    assert air["items"][0]["station_code"] == "BDR"
    assert air["items"][0]["value"] == "30-50"
    assert air["complementary"]["general_public"] == "可如常活動。"


def test_parse_warning_xml_marks_inactive_official_warning():
    xml = """
    <RainstormWarning>
      <System><SysPubdate>2026-05-22 02:30 GMT+8</SysPubdate></System>
      <Custom>
        <Rainstorm>
          <Warncode>NIL</Warncode>
          <Inforce>0</Inforce>
          <Status>0</Status>
          <IssuedAt>2026-05-22 02:30</IssuedAt>
          <Description>現時沒有暴雨警告信號。</Description>
        </Rainstorm>
      </Custom>
    </RainstormWarning>
    """.encode()

    warning = parse_warning_xml(xml, "暴雨", "https://example.test/rainstorm.xml")

    assert warning["status"] == "inactive"
    assert warning["type"] == "暴雨"
    assert warning["message"] == "現時沒有暴雨警告信號。"
