# Writes the local, git-ignored .asset-risk.json read by app/engine/settings.py.
# The keys below are a contract with app/engine/settings.py — change both sides together.
#
# The geolocate module owns the Overture release and its file index, and writes
# vendor/geolocate/.geolocate.json. To change the release, bump the submodule.
#
# NOTE: the Terraform state (terraform.tfstate) holds any AWS credentials in plain text. It is
# git-ignored; keep it that way.

terraform {
  required_version = ">= 1.3"

  required_providers {
    local = {
      source  = "hashicorp/local"
      version = "~> 2.5"
    }
  }
}

module "geolocate" {
  source = "../vendor/geolocate/infra"

  aws_access_key_id     = var.aws_access_key_id
  aws_secret_access_key = var.aws_secret_access_key
  aws_session_token     = var.aws_session_token
}

resource "local_file" "asset_risk_config" {
  filename        = abspath("${path.module}/../.asset-risk.json")
  file_permission = "0600"

  content = jsonencode({
    scenarios             = var.scenarios
    years                 = var.years
    default_building_type = var.default_building_type
    physrisk_batch_size   = var.physrisk_batch_size
    geolocate_workers     = var.geolocate_workers
    geolocate_batch_size  = var.geolocate_batch_size
    cluster_eps_km        = var.cluster_eps_km
    cluster_min_samples   = var.cluster_min_samples
    max_portfolio_rows    = var.max_portfolio_rows
    max_upload_mb         = var.max_upload_mb
    data_dir              = var.data_dir
    api_port              = var.api_port
    geolocate_config      = module.geolocate.config_path
    flood_zones_db        = var.flood_zones_db

    hazard_map_layers       = var.hazard_map_layers
    hazard_map_bucket       = var.hazard_map_bucket
    fire_map_path           = var.fire_map_path
    wind_map_path           = var.wind_map_path
    fire_map_max_zoom       = var.fire_map_max_zoom
    wind_map_max_zoom       = var.wind_map_max_zoom
    hazard_map_alpha        = var.hazard_map_alpha
    hazard_map_legend_stops = var.hazard_map_legend_stops
    hazard_map_array_cache  = var.hazard_map_array_cache
    hazard_map_tile_cache   = var.hazard_map_tile_cache
  })
}
