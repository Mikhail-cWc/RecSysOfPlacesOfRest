-- Работа с геоданными
CREATE EXTENSION IF NOT EXISTS postgis;

-- Таблица мест досуга
CREATE TABLE IF NOT EXISTS places (
    id BIGINT PRIMARY KEY,
    name TEXT NOT NULL,
    city TEXT,
    district TEXT,
    address TEXT,
    rating REAL,
    reviews_count INTEGER DEFAULT 0,
    ratings_count INTEGER DEFAULT 0,
    working_hours TEXT,
    website TEXT,
    phone TEXT,

    location GEOGRAPHY(POINT, 4326),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_places_name ON places USING GIN (to_tsvector('russian', name));
CREATE INDEX IF NOT EXISTS idx_places_district ON places(district);
CREATE INDEX IF NOT EXISTS idx_places_rating ON places(rating DESC);
CREATE INDEX IF NOT EXISTS idx_places_location ON places USING GIST(location);
CREATE INDEX IF NOT EXISTS idx_places_city ON places(city);

-- Таблица тегов
CREATE TABLE IF NOT EXISTS tags (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tags_name ON tags(name);

-- many-to-many связи мест и тегов
CREATE TABLE IF NOT EXISTS place_tags (
    place_id BIGINT NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (place_id, tag_id),
    FOREIGN KEY (place_id) REFERENCES places(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_place_tags_place ON place_tags(place_id);
CREATE INDEX IF NOT EXISTS idx_place_tags_tag ON place_tags(tag_id);

CREATE OR REPLACE VIEW places_with_tags AS
SELECT 
    p.*,
    COALESCE(
        string_agg(t.name, ', ' ORDER BY t.name),
        ''
    ) as tag_list,
    array_agg(t.name ORDER BY t.name) FILTER (WHERE t.name IS NOT NULL) as tags_array
FROM places p
LEFT JOIN place_tags pt ON p.id = pt.place_id
LEFT JOIN tags t ON pt.tag_id = t.id
GROUP BY p.id;

-- Функция для поиска мест рядом с заданными координатами
CREATE OR REPLACE FUNCTION find_places_nearby(
    lat DOUBLE PRECISION,
    lon DOUBLE PRECISION,
    radius_meters INTEGER DEFAULT 5000,
    min_rating REAL DEFAULT 0.0,
    limit_count INTEGER DEFAULT 20
)
RETURNS TABLE (
    id BIGINT,
    name TEXT,
    rating REAL,
    distance_meters DOUBLE PRECISION,
    address TEXT,
    district TEXT,
    tag_list TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        p.id,
        p.name,
        p.rating,
        ST_Distance(
            p.location,
            ST_MakePoint(lon, lat)::geography
        ) as distance_meters,
        p.address,
        p.district,
        pwt.tag_list
    FROM places p
    LEFT JOIN places_with_tags pwt ON p.id = pwt.id
    WHERE p.rating >= min_rating
      AND ST_DWithin(
          p.location,
          ST_MakePoint(lon, lat)::geography,
          radius_meters
      )
    ORDER BY p.rating DESC, distance_meters
    LIMIT limit_count;
END;
$$ LANGUAGE plpgsql;

-- Функция для поиска мест по тегам
CREATE OR REPLACE FUNCTION find_places_by_tags(
    tag_names TEXT[],
    min_rating REAL DEFAULT 0.0,
    limit_count INTEGER DEFAULT 20
)
RETURNS TABLE (
    id BIGINT,
    name TEXT,
    rating REAL,
    address TEXT,
    district TEXT,
    tag_list TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT DISTINCT
        p.id,
        p.name,
        p.rating,
        p.address,
        p.district,
        pwt.tag_list
    FROM places p
    INNER JOIN place_tags pt ON p.id = pt.place_id
    INNER JOIN tags t ON pt.tag_id = t.id
    LEFT JOIN places_with_tags pwt ON p.id = pwt.id
    WHERE p.rating >= min_rating
      AND t.name = ANY(tag_names)
    GROUP BY p.id, p.name, p.rating, p.address, p.district, pwt.tag_list
    HAVING COUNT(DISTINCT t.name) = array_length(tag_names, 1)
    ORDER BY p.rating DESC, p.reviews_count DESC
    LIMIT limit_count;
END;
$$ LANGUAGE plpgsql;

