/// Fare params match the prototype formula agreed in CLAUDE.md. Moves to the
/// backend fare service once /api/v1/bookings/estimate exists — nothing here
/// should be treated as the source of truth for a real charge.
enum VehicleType {
  bike('Bike', baseFare: 30, includedKm: 2, perKmRate: 8, minFare: 40, capacityKg: 20),
  threeWheeler('3-Wheeler',
      baseFare: 60, includedKm: 3, perKmRate: 13, minFare: 80, capacityKg: 500),
  miniTruck('Mini-Truck',
      baseFare: 120, includedKm: 3, perKmRate: 20, minFare: 150, capacityKg: 1250);

  const VehicleType(
    this.label, {
    required this.baseFare,
    required this.includedKm,
    required this.perKmRate,
    required this.minFare,
    required this.capacityKg,
  });

  final String label;
  final double baseFare;
  final double includedKm;
  final double perKmRate;
  final double minFare;
  final int capacityKg;
}
