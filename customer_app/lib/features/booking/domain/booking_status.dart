enum BookingStatus { searching, driverAssigned, pickedUp, delivered }

class AssignedDriver {
  const AssignedDriver({
    required this.name,
    required this.vehicleNumber,
    required this.rating,
  });

  final String name;
  final String vehicleNumber;
  final double rating;
}
