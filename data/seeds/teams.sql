-- MLB 30개 구단 시드 데이터
-- docker-compose.yml의 /docker-entrypoint-initdb.d/ 에서 자동 실행
-- 이미 데이터가 있으면 무시 (ON CONFLICT DO NOTHING)

INSERT INTO teams (league, name, short_name, city, stadium_name, stadium_lat, stadium_lon, park_factor, roof_type) VALUES
  ('MLB', 'Arizona Diamondbacks', 'ARI', 'Phoenix', 'Chase Field', 33.4453, -112.0667, 1.043, 'retractable'),
  ('MLB', 'Atlanta Braves', 'ATL', 'Atlanta', 'Truist Park', 33.8908, -84.4678, 1.021, 'open'),
  ('MLB', 'Baltimore Orioles', 'BAL', 'Baltimore', 'Oriole Park at Camden Yards', 39.2838, -76.6218, 0.985, 'open'),
  ('MLB', 'Boston Red Sox', 'BOS', 'Boston', 'Fenway Park', 42.3467, -71.0972, 1.030, 'open'),
  ('MLB', 'Chicago Cubs', 'CHC', 'Chicago', 'Wrigley Field', 41.9484, -87.6553, 0.993, 'open'),
  ('MLB', 'Chicago White Sox', 'CWS', 'Chicago', 'Guaranteed Rate Field', 41.8299, -87.6338, 0.980, 'open'),
  ('MLB', 'Cincinnati Reds', 'CIN', 'Cincinnati', 'Great American Ball Park', 39.0975, -84.5080, 1.076, 'open'),
  ('MLB', 'Cleveland Guardians', 'CLE', 'Cleveland', 'Progressive Field', 41.4962, -81.6852, 0.984, 'open'),
  ('MLB', 'Colorado Rockies', 'COL', 'Denver', 'Coors Field', 39.7559, -104.9942, 1.227, 'open'),
  ('MLB', 'Detroit Tigers', 'DET', 'Detroit', 'Comerica Park', 42.3390, -83.0485, 0.967, 'open'),
  ('MLB', 'Houston Astros', 'HOU', 'Houston', 'Minute Maid Park', 29.7572, -95.3552, 1.010, 'retractable'),
  ('MLB', 'Kansas City Royals', 'KC', 'Kansas City', 'Kauffman Stadium', 39.0517, -94.4803, 0.990, 'open'),
  ('MLB', 'Los Angeles Angels', 'LAA', 'Anaheim', 'Angel Stadium', 33.8003, -117.8827, 1.000, 'open'),
  ('MLB', 'Los Angeles Dodgers', 'LAD', 'Los Angeles', 'Dodger Stadium', 34.0739, -118.2400, 1.017, 'open'),
  ('MLB', 'Miami Marlins', 'MIA', 'Miami', 'loanDepot park', 25.7781, -80.2197, 0.952, 'retractable'),
  ('MLB', 'Milwaukee Brewers', 'MIL', 'Milwaukee', 'American Family Field', 43.0280, -87.9712, 0.985, 'retractable'),
  ('MLB', 'Minnesota Twins', 'MIN', 'Minneapolis', 'Target Field', 44.9817, -93.2781, 0.975, 'open'),
  ('MLB', 'New York Mets', 'NYM', 'New York', 'Citi Field', 40.7571, -73.8458, 0.992, 'open'),
  ('MLB', 'New York Yankees', 'NYY', 'New York', 'Yankee Stadium', 40.8296, -73.9262, 1.039, 'open'),
  ('MLB', 'Oakland Athletics', 'OAK', 'Oakland', 'Oakland Coliseum', 37.7516, -122.2005, 0.946, 'open'),
  ('MLB', 'Philadelphia Phillies', 'PHI', 'Philadelphia', 'Citizens Bank Park', 39.9061, -75.1665, 1.028, 'open'),
  ('MLB', 'Pittsburgh Pirates', 'PIT', 'Pittsburgh', 'PNC Park', 40.4469, -80.0057, 0.981, 'open'),
  ('MLB', 'San Diego Padres', 'SD', 'San Diego', 'Petco Park', 32.7076, -117.1570, 0.953, 'open'),
  ('MLB', 'San Francisco Giants', 'SF', 'San Francisco', 'Oracle Park', 37.7786, -122.3893, 0.926, 'open'),
  ('MLB', 'Seattle Mariners', 'SEA', 'Seattle', 'T-Mobile Park', 47.5914, -122.3325, 0.973, 'retractable'),
  ('MLB', 'St. Louis Cardinals', 'STL', 'St. Louis', 'Busch Stadium', 38.6226, -90.1928, 0.983, 'open'),
  ('MLB', 'Tampa Bay Rays', 'TB', 'St. Petersburg', 'Tropicana Field', 27.7683, -82.6534, 0.961, 'dome'),
  ('MLB', 'Texas Rangers', 'TEX', 'Arlington', 'Globe Life Field', 32.7473, -97.0827, 1.008, 'retractable'),
  ('MLB', 'Toronto Blue Jays', 'TOR', 'Toronto', 'Rogers Centre', 43.6414, -79.3894, 0.994, 'retractable'),
  ('MLB', 'Washington Nationals', 'WSH', 'Washington D.C.', 'Nationals Park', 38.8730, -77.0074, 0.992, 'open')
ON CONFLICT (league, short_name) DO NOTHING;

-- KBO 10개 구단 시드 데이터
INSERT INTO teams (league, name, short_name, city, stadium_name, stadium_lat, stadium_lon, park_factor, roof_type) VALUES
  ('KBO', 'KIA 타이거즈', 'KIA', '광주', '광주-기아 챔피언스 필드', 35.1685, 126.8889, 1.010, 'open'),
  ('KBO', '삼성 라이온즈', '삼성', '대구', '라이온즈 파크', 35.8413, 128.6817, 0.995, 'open'),
  ('KBO', 'LG 트윈스', 'LG', '서울', '잠실야구장', 37.5122, 127.0717, 1.005, 'open'),
  ('KBO', '두산 베어스', '두산', '서울', '잠실야구장', 37.5122, 127.0717, 1.005, 'open'),
  ('KBO', '한화 이글스', '한화', '대전', '한화생명 이글스파크', 36.3172, 127.4295, 0.990, 'open'),
  ('KBO', 'SSG 랜더스', 'SSG', '인천', '인천SSG랜더스필드', 37.4370, 126.6931, 0.985, 'open'),
  ('KBO', '롯데 자이언츠', '롯데', '부산', '사직야구장', 35.1939, 129.0614, 1.000, 'open'),
  ('KBO', '키움 히어로즈', '키움', '서울', '고척스카이돔', 37.4982, 126.8670, 0.975, 'dome'),
  ('KBO', 'NC 다이노스', 'NC', '창원', '창원NC파크', 35.2225, 128.5817, 1.015, 'open'),
  ('KBO', 'KT 위즈', 'KT', '수원', '수원KT위즈파크', 37.2998, 127.0097, 1.000, 'open')
ON CONFLICT (league, short_name) DO NOTHING;
