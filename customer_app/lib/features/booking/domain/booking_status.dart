/// Mirrors the server's `booking_status` enum, name for name.
///
/// `cancelled` and `expired` were missing before spec 011, and their absence
/// was not a cosmetic gap: [Booking.fromJson] threw an ArgumentError on either
/// one, so the moment a booking expired the status screen crashed rather than
/// telling the customer no driver was found.
///
/// Deliberately named after the server's values rather than the UI's ("pending"
/// not "searching"). One vocabulary across the wire and the app means one less
/// translation table to keep in step.
enum BookingStatus {
  pending,
  driverAssigned,
  pickedUp,
  delivered,
  cancelled,
  expired;

  /// Nothing will change from here, so polling should stop for good.
  bool get isTerminal =>
      this == BookingStatus.delivered ||
      this == BookingStatus.cancelled ||
      this == BookingStatus.expired;

  /// The trip is live: a driver is committed and the goods are moving.
  bool get isActive =>
      this == BookingStatus.driverAssigned || this == BookingStatus.pickedUp;

  /// The server accepts a customer cancel only from these two. Mirrored here
  /// so the button is hidden rather than shown and then 409-ing — once the
  /// goods are picked up, cancelling is a support matter.
  bool get isCancellable =>
      this == BookingStatus.pending || this == BookingStatus.driverAssigned;
}
