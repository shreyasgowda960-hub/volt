class VehicleTypeOption {
  const VehicleTypeOption({
    required this.code,
    required this.label,
    required this.capacityKg,
  });

  final String code;
  final String label;
  final int capacityKg;

  factory VehicleTypeOption.fromJson(Map<String, dynamic> json) {
    return VehicleTypeOption(
      code: json['code'] as String,
      label: json['label'] as String,
      capacityKg: json['capacity_kg'] as int,
    );
  }
}
