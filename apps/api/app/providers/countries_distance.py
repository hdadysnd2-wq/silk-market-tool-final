"""Static logistics-proximity reference: great-circle km from Jeddah per market.

Feeds the engine's ``logistics_proximity`` scoring component (J1) from REAL,
derivable data: each of the ~80 largest importing markets carries the coordinates
of its main container port (or, for a landlocked market, its main freight
gateway city), and the distance is COMPUTED at import time as the haversine
great-circle distance from Jeddah Islamic Port (KSA) — numbers are derived from
the coordinate table below, never typed in by hand. Great-circle understates an
actual sea route (it cuts across land), which is why the source label says
exactly what it is: ``haversine(Jeddah→main port)``. A market absent from the
table is a declared gap (I1) — the component is omitted, never estimated.
"""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

#: Source label stamped on every logistics_proximity component (honest method).
DISTANCE_SOURCE = "haversine(Jeddah→main port)"

#: Jeddah Islamic Port, Saudi Arabia — the KSA export baseline.
JEDDAH_LAT_LON: tuple[float, float] = (21.48, 39.17)

#: ISO3 -> (main port / freight gateway, latitude, longitude).
#: Approximate port coordinates (decimal degrees) for the world's largest
#: importing markets; landlocked markets use their main freight hub city.
PORT_COORDS: dict[str, tuple[str, float, float]] = {
    "SAU": ("Jeddah Islamic Port", 21.48, 39.17),
    # --- Gulf / Middle East ---------------------------------------------
    "ARE": ("Jebel Ali (Dubai)", 25.01, 55.06),
    "QAT": ("Hamad Port (Doha)", 25.00, 51.61),
    "KWT": ("Shuwaikh (Kuwait City)", 29.35, 47.93),
    "BHR": ("Khalifa Bin Salman", 26.15, 50.65),
    "OMN": ("Sohar", 24.51, 56.61),
    "JOR": ("Aqaba", 29.52, 35.00),
    "IRQ": ("Umm Qasr", 30.03, 47.94),
    "IRN": ("Bandar Abbas", 27.14, 56.21),
    "ISR": ("Haifa", 32.82, 35.00),
    "LBN": ("Beirut", 33.90, 35.52),
    "SYR": ("Latakia", 35.52, 35.78),
    "YEM": ("Aden", 12.79, 44.97),
    "TUR": ("Ambarlı (Istanbul)", 40.97, 28.69),
    # --- Africa ----------------------------------------------------------
    "EGY": ("Alexandria", 31.18, 29.88),
    "SDN": ("Port Sudan", 19.61, 37.22),
    "DJI": ("Djibouti", 11.60, 43.15),
    "ETH": ("via Djibouti", 11.60, 43.15),
    "SOM": ("Mogadishu", 2.03, 45.34),
    "KEN": ("Mombasa", -4.06, 39.65),
    "TZA": ("Dar es Salaam", -6.82, 39.29),
    "ZAF": ("Durban", -29.87, 31.02),
    "NGA": ("Lagos (Apapa)", 6.44, 3.39),
    "GHA": ("Tema", 5.64, 0.01),
    "CIV": ("Abidjan", 5.28, -4.01),
    "SEN": ("Dakar", 14.68, -17.43),
    "AGO": ("Luanda", -8.79, 13.24),
    "MAR": ("Tanger Med", 35.88, -5.50),
    "DZA": ("Algiers", 36.77, 3.06),
    "TUN": ("Radès (Tunis)", 36.80, 10.28),
    "LBY": ("Tripoli", 32.90, 13.19),
    # --- Europe ----------------------------------------------------------
    "DEU": ("Hamburg", 53.55, 9.97),
    "NLD": ("Rotterdam", 51.95, 4.14),
    "BEL": ("Antwerp", 51.23, 4.40),
    "FRA": ("Le Havre", 49.49, 0.11),
    "GBR": ("Felixstowe", 51.96, 1.35),
    "IRL": ("Dublin", 53.35, -6.21),
    "ESP": ("Valencia", 39.45, -0.32),
    "PRT": ("Lisbon", 38.70, -9.16),
    "ITA": ("Genoa", 44.40, 8.93),
    "GRC": ("Piraeus", 37.94, 23.63),
    "MLT": ("Marsaxlokk", 35.83, 14.54),
    "CYP": ("Limassol", 34.65, 33.02),
    "POL": ("Gdańsk", 54.40, 18.67),
    "CZE": ("Prague (freight hub)", 50.09, 14.42),
    "SVK": ("Bratislava (freight hub)", 48.14, 17.11),
    "AUT": ("Vienna (freight hub)", 48.21, 16.37),
    "CHE": ("Basel (Rhine hub)", 47.56, 7.59),
    "LUX": ("Luxembourg (freight hub)", 49.61, 6.13),
    "HUN": ("Budapest (freight hub)", 47.50, 19.05),
    "ROU": ("Constanța", 44.17, 28.65),
    "BGR": ("Varna", 43.19, 27.91),
    "SRB": ("Belgrade (Danube hub)", 44.82, 20.46),
    "HRV": ("Rijeka", 45.33, 14.44),
    "SVN": ("Koper", 45.55, 13.73),
    "DNK": ("Aarhus", 56.15, 10.22),
    "SWE": ("Gothenburg", 57.70, 11.90),
    "NOR": ("Oslo", 59.90, 10.74),
    "FIN": ("Helsinki", 60.15, 24.95),
    "EST": ("Tallinn", 59.44, 24.77),
    "LVA": ("Riga", 56.97, 24.10),
    "LTU": ("Klaipėda", 55.71, 21.13),
    "UKR": ("Odesa", 46.49, 30.74),
    "RUS": ("St. Petersburg", 59.90, 30.25),
    # --- Asia ------------------------------------------------------------
    "CHN": ("Shanghai (Yangshan)", 31.23, 121.49),
    "HKG": ("Hong Kong (Kwai Tsing)", 22.30, 114.17),
    "TWN": ("Kaohsiung", 22.61, 120.28),
    "JPN": ("Tokyo", 35.61, 139.79),
    "KOR": ("Busan", 35.10, 129.04),
    "IND": ("Nhava Sheva (Mumbai)", 18.95, 72.95),
    "PAK": ("Karachi", 24.79, 66.98),
    "BGD": ("Chattogram", 22.31, 91.80),
    "LKA": ("Colombo", 6.95, 79.85),
    "MMR": ("Yangon", 16.77, 96.19),
    "THA": ("Laem Chabang", 13.08, 100.88),
    "KHM": ("Sihanoukville", 10.63, 103.50),
    "VNM": ("Ho Chi Minh City", 10.77, 106.72),
    "MYS": ("Port Klang", 3.00, 101.39),
    "SGP": ("Singapore", 1.26, 103.84),
    "IDN": ("Tanjung Priok (Jakarta)", -6.10, 106.89),
    "PHL": ("Manila", 14.60, 120.97),
    "KAZ": ("Almaty (freight hub)", 43.24, 76.89),
    "UZB": ("Tashkent (freight hub)", 41.30, 69.24),
    # --- Americas --------------------------------------------------------
    "USA": ("New York / New Jersey", 40.67, -74.05),
    "CAN": ("Montreal", 45.50, -73.55),
    "MEX": ("Veracruz", 19.20, -96.13),
    "GTM": ("Puerto Quetzal", 13.92, -90.79),
    "PAN": ("Balboa", 8.95, -79.57),
    "DOM": ("Caucedo", 18.42, -69.63),
    "COL": ("Cartagena", 10.40, -75.51),
    "VEN": ("Puerto Cabello", 10.48, -68.01),
    "ECU": ("Guayaquil", -2.28, -79.91),
    "PER": ("Callao", -12.05, -77.14),
    "BRA": ("Santos", -23.98, -46.29),
    "CHL": ("San Antonio", -33.59, -71.61),
    "ARG": ("Buenos Aires", -34.58, -58.37),
    "URY": ("Montevideo", -34.90, -56.21),
    # --- Oceania ---------------------------------------------------------
    "AUS": ("Sydney (Port Botany)", -33.96, 151.20),
    "NZL": ("Auckland", -36.84, 174.77),
}

#: Mean Earth radius, km (haversine constant).
_EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two (lat, lon) points in km."""
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2.0) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2.0) ** 2
    return 2.0 * _EARTH_RADIUS_KM * asin(sqrt(a))


def _derive_distances() -> dict[str, float]:
    """Compute every market's distance from Jeddah at import time (derived data)."""
    jlat, jlon = JEDDAH_LAT_LON
    return {
        iso3: round(haversine_km(jlat, jlon, lat, lon), 0)
        for iso3, (_port, lat, lon) in PORT_COORDS.items()
    }


#: ISO3 -> derived great-circle km from Jeddah (computed, not hand-entered).
DISTANCE_KM_FROM_JEDDAH: dict[str, float] = _derive_distances()


def distance_from_jeddah_km(iso3: str) -> float | None:
    """Distance in km from Jeddah to the market's main port; None = declared gap."""
    return DISTANCE_KM_FROM_JEDDAH.get((iso3 or "").upper())


def main_port(iso3: str) -> str | None:
    """The reference port/gateway the distance was computed to (provenance)."""
    entry = PORT_COORDS.get((iso3 or "").upper())
    return entry[0] if entry else None
