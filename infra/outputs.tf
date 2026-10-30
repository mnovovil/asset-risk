output "config_path" {
  description = "Path of the generated .asset-risk.json."
  value       = local_file.asset_risk_config.filename
}

output "geolocate_config_path" {
  description = "Path of the generated .geolocate.json."
  value       = module.geolocate.config_path
}

output "overture_buildings_path" {
  description = "Overture buildings release that geolocate reads."
  value       = module.geolocate.overture_buildings_path
}

output "file_index_active" {
  description = "Whether geolocate's file index matches its release. If false, every point scans the whole folder."
  value       = module.geolocate.file_index_active
}
