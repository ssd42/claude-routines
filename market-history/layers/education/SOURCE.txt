NJ ZIP/ZCTA EDUCATION RATES — DATA DICTIONARY AND METHODOLOGY

FILE
nj_zip_education_rates_2020_2024.csv

ROW COUNT
598 New Jersey Census ZIP Code Tabulation Areas (ZCTAs).

EDUCATION DATA
Source: U.S. Census Bureau, 2020–2024 American Community Survey 5-year estimates.
Table: B15003, Educational Attainment for the Population 25 Years and Over.

Measures:
- high_school_graduate_or_higher_pct_age_25_plus:
  Percentage of residents age 25+ whose highest attainment is a regular high-school
  diploma, GED/alternative credential, some college, associate's degree, bachelor's
  degree, master's degree, professional degree, or doctorate.
- bachelors_degree_or_higher_pct_age_25_plus:
  Percentage of residents age 25+ with a bachelor's, master's, professional, or
  doctorate degree.
- population_age_25_plus:
  The ACS denominator used for both percentages.

GEOGRAPHY MAPPING
ZIP codes are represented by 2020 Census ZIP Code Tabulation Areas (ZCTAs).
A ZCTA may cross more than one municipality or county.

Primary mapping rule:
1. Primary county = county with the largest share of the ZCTA's 2020 land area.
2. Primary municipality = municipality/county subdivision with the largest ZCTA
   land overlap inside that primary county.

The CSV also includes:
- primary municipality and county land-share percentages;
- counts of municipalities and counties spanned;
- all overlapping municipalities and counties.

IMPORTANT LIMITATIONS
- ZCTAs approximate USPS ZIP-code service areas; they are not official USPS delivery
  boundaries.
- Some USPS ZIP codes, especially PO-box-only or organization-specific ZIP codes,
  do not have a Census ZCTA and therefore cannot have residential ACS education rates.
- The municipality assignment is a geographic-overlap rule, not a USPS mailing-city
  designation.
- Four NJ ZCTAs have an ACS age-25+ denominator of zero; their education percentages
  are left blank.

SOURCE FILES
Education:
https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/5YRData/acsdt5y2024-b15003.dat

2020 ZCTA relationship files:
https://www.census.gov/geographies/reference-files/time-series/geo/relationship-files.2020.html
