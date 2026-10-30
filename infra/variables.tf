variable "scenarios" {
  description = "Climate scenarios to assess. The historical baseline always comes back too. Data differs by scenario: ssp585 has all five hazards, ssp245 lacks fire and hail, ssp126 has only fire and hail, and ssp370 returned nothing."
  type        = list(string)
  default     = ["ssp245", "ssp585"]

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
  description = "Projection years to assess. Each scenario and year pair is one physrisk calculation."
  type        = list(number)
  default     = [2030, 2050, 2080]

  validation {
    condition = (
      length(var.years) > 0
      && length(distinct(var.years)) == length(var.years)
      && alltrue([for y in var.years : y == floor(y) && y >= 2020 && y <= 2100])
    )
    error_message = "years must be distinct whole years from 2020 to 2100."
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
