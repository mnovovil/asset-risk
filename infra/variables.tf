variable "scenarios" {
  description = "Climate scenarios to assess. The historical baseline always comes back too. Data differs by scenario: ssp585 has all five hazards, ssp245 lacks fire and hail, ssp126 has only fire and hail, and ssp370 returned nothing."
  type        = list(string)
  default     = ["ssp126", "ssp245", "ssp585"]

  validation {
    condition = (
      length(var.scenarios) > 0
      && length(distinct(var.scenarios)) == length(var.scenarios)
      && alltrue([for s in var.scenarios : contains(["ssp126", "ssp245", "ssp370", "ssp585"], s)])
    )
    error_message = "scenarios must be distinct values from ssp126, ssp245, ssp370, ssp585."
  }
}

variable "years" {
  description = "Projection years to assess, from 2030, 2050 and 2080. 2025 returns no losses from physrisk; present-day risk is the historical baseline, which always comes back. Each scenario and year pair is one physrisk calculation."
  type        = list(number)
  default     = [2030, 2050, 2080]

  validation {
    condition = (
      length(var.years) > 0
      && length(distinct(var.years)) == length(var.years)
      && alltrue([for y in var.years : contains([2030, 2050, 2080], y)])
    )
    error_message = "years must be distinct values from 2030, 2050, 2080."
  }
}

variable "default_building_type" {
  description = "physrisk type for assets with no usable Overture class or subtype. Most Overture buildings have neither, so this often decides the type, and results are sensitive to it."
  type        = string
  default     = "Buildings/Commercial"

  validation {
    condition     = contains(["Buildings/Commercial", "Buildings/Industrial", "Buildings/Residential"], var.default_building_type)
    error_message = "default_building_type must be Buildings/Commercial, Buildings/Industrial or Buildings/Residential."
  }
}

variable "physrisk_batch_size" {
  description = "Assets per physrisk request."
  type        = number
  default     = 100

  validation {
    condition     = var.physrisk_batch_size >= 1 && var.physrisk_batch_size == floor(var.physrisk_batch_size)
    error_message = "physrisk_batch_size must be a whole number of at least 1."
  }
}

variable "geolocate_workers" {
  description = "Threads matching batches of points in geolocate. Lower it if you see S3 errors."
  type        = number
  default     = 16

  validation {
    condition     = var.geolocate_workers >= 1 && var.geolocate_workers == floor(var.geolocate_workers)
    error_message = "geolocate_workers must be a whole number of at least 1."
  }
}

variable "geolocate_batch_size" {
  description = "Points per geolocate batch. Progress updates once per batch."
  type        = number
  default     = 20

  validation {
    condition     = var.geolocate_batch_size >= 1 && var.geolocate_batch_size == floor(var.geolocate_batch_size)
    error_message = "geolocate_batch_size must be a whole number of at least 1."
  }
}

variable "cluster_eps_km" {
  description = "DBSCAN neighbourhood radius for the map's risk-concentration bubbles, in km."
  type        = number
  default     = 50

  validation {
    condition     = var.cluster_eps_km > 0 && var.cluster_eps_km <= 1000
    error_message = "cluster_eps_km must be more than 0 and at most 1000."
  }
}

variable "cluster_min_samples" {
  description = "Assets within cluster_eps_km of a point, itself included, for DBSCAN to start a cluster there."
  type        = number
  default     = 5

  validation {
    condition     = var.cluster_min_samples >= 2 && var.cluster_min_samples == floor(var.cluster_min_samples)
    error_message = "cluster_min_samples must be a whole number of at least 2."
  }
}

variable "max_portfolio_rows" {
  description = "Largest portfolio accepted, in rows."
  type        = number
  default     = 5000

  validation {
    condition     = var.max_portfolio_rows >= 1 && var.max_portfolio_rows == floor(var.max_portfolio_rows)
    error_message = "max_portfolio_rows must be a whole number of at least 1."
  }
}

variable "max_upload_mb" {
  description = "Largest CSV upload accepted, in megabytes."
  type        = number
  default     = 10

  validation {
    condition     = var.max_upload_mb > 0
    error_message = "max_upload_mb must be positive."
  }
}

variable "data_dir" {
  description = "Folder for run outputs. A relative path is relative to the repo root."
  type        = string
  default     = "data"

  validation {
    condition     = trimspace(var.data_dir) != ""
    error_message = "data_dir must not be empty."
  }
}

variable "flood_zones_db" {
  description = "FEMA flood zone database built by script/build_flood_zones.py. A relative path is relative to the repo root. null turns the flood zone lookup off. A run without the file reports the zones as unavailable."
  type        = string
  default     = "data/fema/flood-zones.duckdb"
  nullable    = true

  validation {
    condition     = var.flood_zones_db == null ? true : trimspace(var.flood_zones_db) != ""
    error_message = "flood_zones_db must be null or a non-empty path."
  }
}

variable "api_port" {
  description = "Port the app listens on."
  type        = number
  default     = 8000

  validation {
    condition     = var.api_port >= 1 && var.api_port <= 65535 && var.api_port == floor(var.api_port)
    error_message = "api_port must be a whole number from 1 to 65535."
  }
}

variable "aws_access_key_id" {
  description = "Optional AWS access key ID, passed to geolocate. Leave empty to read Overture anonymously."
  type        = string
  default     = ""
  sensitive   = true
}

variable "aws_secret_access_key" {
  description = "Optional AWS secret access key, passed to geolocate."
  type        = string
  default     = ""
  sensitive   = true
}

variable "aws_session_token" {
  description = "Optional AWS session token, passed to geolocate."
  type        = string
  default     = ""
  sensitive   = true
}

# --- Hazard maps (the asset panel's map). What the data is (its colours, return period, layout and
# physrisk's scaling) stays in app/engine; these are run settings. Defaults reproduce the code's.

variable "hazard_map_layers" {
  description = "Hazard map layers to offer, from RiverineInundation, CoastalInundation, Fire and Wind. An empty list turns the maps off."
  type        = list(string)
  default     = ["RiverineInundation", "CoastalInundation", "Fire", "Wind"]

  validation {
    condition = (
      length(distinct(var.hazard_map_layers)) == length(var.hazard_map_layers)
      && alltrue([for l in var.hazard_map_layers : contains(["RiverineInundation", "CoastalInundation", "Fire", "Wind"], l)])
    )
    error_message = "hazard_map_layers must be distinct values from RiverineInundation, CoastalInundation, Fire, Wind."
  }
}

variable "hazard_map_bucket" {
  description = "Bucket and folder holding physrisk's hazard zarr, read anonymously for the wildfire and wind maps. No s3:// prefix."
  type        = string
  default     = "os-climate-physical-risk/hazard-indicators/hazard.zarr"

  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9_.-]*(/[A-Za-z0-9_.-]+)*$", var.hazard_map_bucket))
    error_message = "hazard_map_bucket must be a bucket and folder, like my-bucket/hazard.zarr, with no s3:// prefix."
  }
}

variable "fire_map_path" {
  description = "Wildfire array path in the bucket, with {scenario} and {year}. It must be a Fire resource in physrisk's inventory, or the maps return 502."
  type        = string
  default     = "fire/jupiter/v1/fire_probability_{scenario}_{year}"

  validation {
    condition = (
      length(regexall("\\{scenario\\}", var.fire_map_path)) == 1
      && length(regexall("\\{year\\}", var.fire_map_path)) == 1
      && can(regex("^[A-Za-z0-9_.-][A-Za-z0-9_./-]*$", replace(replace(var.fire_map_path, "{scenario}", "s"), "{year}", "y")))
    )
    error_message = "fire_map_path must contain {scenario} and {year} once each, and otherwise only letters, digits and _ . - /."
  }
}

variable "wind_map_path" {
  description = "Tropical cyclone wind array path in the bucket, with {scenario} and {year}. It must be a Wind resource in physrisk's inventory, or the maps return 502."
  type        = string
  default     = "wind/iris/v1/max_speed_{scenario}_{year}"

  validation {
    condition = (
      length(regexall("\\{scenario\\}", var.wind_map_path)) == 1
      && length(regexall("\\{year\\}", var.wind_map_path)) == 1
      && can(regex("^[A-Za-z0-9_.-][A-Za-z0-9_./-]*$", replace(replace(var.wind_map_path, "{scenario}", "s"), "{year}", "y")))
    )
    error_message = "wind_map_path must contain {scenario} and {year} once each, and otherwise only letters, digits and _ . - /."
  }
}

variable "fire_map_max_zoom" {
  description = "Deepest zoom with wildfire tiles. A 0.25 degree cell is about 23 px at zoom 6, so deeper adds nothing."
  type        = number
  default     = 6

  validation {
    condition     = var.fire_map_max_zoom >= 0 && var.fire_map_max_zoom <= 10 && var.fire_map_max_zoom == floor(var.fire_map_max_zoom)
    error_message = "fire_map_max_zoom must be a whole number from 0 to 10."
  }
}

variable "wind_map_max_zoom" {
  description = "Deepest zoom with wind tiles. A 0.1 degree cell is about 18 px at zoom 7, so deeper adds nothing."
  type        = number
  default     = 7

  validation {
    condition     = var.wind_map_max_zoom >= 0 && var.wind_map_max_zoom <= 10 && var.wind_map_max_zoom == floor(var.wind_map_max_zoom)
    error_message = "wind_map_max_zoom must be a whole number from 0 to 10."
  }
}

variable "hazard_map_alpha" {
  description = "Opacity of the wildfire and wind tiles, 1 to 255. physrisk draws the flood tiles at 200 itself."
  type        = number
  default     = 200

  validation {
    condition     = var.hazard_map_alpha >= 1 && var.hazard_map_alpha <= 255 && var.hazard_map_alpha == floor(var.hazard_map_alpha)
    error_message = "hazard_map_alpha must be a whole number from 1 to 255."
  }
}

variable "hazard_map_legend_stops" {
  description = "Colours in the wildfire and wind legends' gradient."
  type        = number
  default     = 9

  validation {
    condition     = var.hazard_map_legend_stops >= 2 && var.hazard_map_legend_stops <= 33 && var.hazard_map_legend_stops == floor(var.hazard_map_legend_stops)
    error_message = "hazard_map_legend_stops must be a whole number from 2 to 33."
  }
}

variable "hazard_map_array_cache" {
  description = "Arrays kept in memory per layer, one per scenario and year. A wildfire array is about 4 MB and a wind one about 17 MB."
  type        = number
  default     = 4

  validation {
    condition     = var.hazard_map_array_cache >= 1 && var.hazard_map_array_cache == floor(var.hazard_map_array_cache)
    error_message = "hazard_map_array_cache must be a whole number of at least 1."
  }
}

variable "hazard_map_tile_cache" {
  description = "Tiles kept in memory per layer."
  type        = number
  default     = 256

  validation {
    condition     = var.hazard_map_tile_cache >= 1 && var.hazard_map_tile_cache == floor(var.hazard_map_tile_cache)
    error_message = "hazard_map_tile_cache must be a whole number of at least 1."
  }
}
