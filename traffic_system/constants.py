"""Constants used throughout the traffic monitoring system."""

# Congestion thresholds (0-100 scale)
CONGESTION_LOW = 30
CONGESTION_MEDIUM = 60
CONGESTION_HIGH = 80

# Number of drones to deploy per traffic-jam route
DRONES_PER_JAM_ROUTE = 1

# Minimum drone battery level required to deploy (percentage)
MIN_BATTERY_TO_DEPLOY = 20

# Drone battery drain rates (percentage per operation)
BATTERY_DRAIN_DEPLOY = 5
BATTERY_DRAIN_MANAGE = 2
BATTERY_DRAIN_RETURN = 3

# Human officer estimated arrival time (minutes)
HUMAN_OFFICER_ETA_MINUTES = 15
