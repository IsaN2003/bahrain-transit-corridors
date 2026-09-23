r"""country_coords.py — ISO-2 country centroids (lat, lon) for the flow map."""

# Lookup table: ISO-2 code -> approximate geographic centre (latitude, longitude).
# Used to place trade-flow endpoints on the map; packed several per line for compactness.
COUNTRY_COORDS = {
    "BH": (26.07, 50.56),   # Bahrain — the hub
    "JP": (36.20, 138.25),  "DE": (51.17, 10.45),  "CN": (35.86, 104.20),
    "US": (37.09, -95.71),  "SA": (23.89, 45.08),  "AE": (23.42, 53.85),
    "TH": (15.87, 100.99),  "KR": (35.91, 127.77), "IN": (20.59, 78.96),
    "GB": (55.38, -3.44),   "IT": (41.87, 12.57),  "FR": (46.23, 2.21),
    "NL": (52.13, 5.29),    "KW": (29.31, 47.48),  "QA": (25.35, 51.18),
    "OM": (21.47, 55.98),   "IQ": (33.22, 43.68),  "JO": (30.59, 36.24),
    "EG": (26.82, 30.80),   "LB": (33.85, 35.86),  "YE": (15.55, 48.52),
    "PK": (30.38, 69.35),   "BD": (23.69, 90.36),  "TR": (38.96, 35.24),
    "ES": (40.46, -3.75),   "BE": (50.50, 4.47),   "CH": (46.82, 8.23),
    "SE": (60.13, 18.64),   "PL": (51.92, 19.15),  "CZ": (49.82, 15.47),
    "AT": (47.52, 14.55),   "ID": (-0.79, 113.92), "MY": (4.21, 101.98),
    "SG": (1.35, 103.82),   "VN": (14.06, 108.28), "PH": (12.88, 121.77),
    "AU": (-25.27, 133.78), "ZA": (-30.56, 22.94), "BR": (-14.24, -51.93),
    "CA": (56.13, -106.35), "MX": (23.63, -102.55),"RU": (61.52, 105.32),
    "TW": (23.70, 120.96),  "HK": (22.32, 114.17), "IR": (32.43, 53.69),
    "LK": (7.87, 80.77),    "MA": (31.79, -7.09),  "TN": (33.89, 9.54),
    "DZ": (28.03, 1.66),    "SD": (12.86, 30.22),  "NG": (9.08, 8.68),
    "KE": (-0.02, 37.91),   "ET": (9.15, 40.49),   "GH": (7.95, -1.02),
    "PT": (39.40, -8.22),   "GR": (39.07, 21.82),  "RO": (45.94, 24.97),
    "HU": (47.16, 19.50),   "FI": (61.92, 25.75),  "NO": (60.47, 8.47),
    "DK": (56.26, 9.50),    "IE": (53.41, -8.24),  "UA": (48.38, 31.17),
    "AZ": (40.14, 47.58),   "GE": (42.32, 43.36),  "KZ": (48.02, 66.92),
    "NZ": (-40.90, 174.89), "AR": (-38.42, -63.62),"CL": (-35.68, -71.54),
    "CO": (4.57, -74.30),   "IL": (31.05, 34.85),  "SY": (34.80, 39.00),
    "AF": (33.94, 67.71),   "MM": (21.92, 95.96),  "KH": (12.57, 104.99),
    "NP": (28.39, 84.12),   "DJ": (11.83, 42.59),  "SO": (5.15, 46.20),
    "BH_": (26.07, 50.56),  # Alias for Bahrain (same point as "BH")
}


def add_coords(df):
    """Attach origin/destination lat-lon columns; rows with an unknown code get NaN."""
    df = df.copy()  # avoid mutating the caller's DataFrame
    # Look up each code; unknown codes fall back to (None, None) -> NaN in the column.
    # [0] picks latitude, [1] picks longitude.
    df["o_lat"] = df["origin"].map(lambda c: COUNTRY_COORDS.get(c, (None, None))[0])
    df["o_lon"] = df["origin"].map(lambda c: COUNTRY_COORDS.get(c, (None, None))[1])
    df["d_lat"] = df["dest"].map(lambda c: COUNTRY_COORDS.get(c, (None, None))[0])
    df["d_lon"] = df["dest"].map(lambda c: COUNTRY_COORDS.get(c, (None, None))[1])
    return df