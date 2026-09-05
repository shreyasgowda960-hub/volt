import 'package:flutter/material.dart';

/// The VOLT palette, sampled from the logo (spec 016).
///
/// Screens reference these tokens and never write a raw `Color(0x...)`. That
/// is not tidiness: a dark theme is a planned second `ColorScheme`, and it is
/// only cheap if no screen has its own opinion about colour.
///
/// Light only, by decision. Dark is deferred — see docs/future-plans.md.
abstract final class AppColors {
  // --- Base -------------------------------------------------------------
  // Off-white rather than pure #FFF. Pure white glares outdoors, which
  // matters because drivers use this in daylight.
  static const background = Color(0xFFFAFAFB);
  static const surface = Color(0xFFFFFFFF);
  static const surfaceSunken = Color(0xFFF1F2F4);
  static const border = Color(0xFFE2E4E8);

  // --- Brand navy -------------------------------------------------------
  // From the logo. Headers, body text, secondary actions.
  static const navy = Color(0xFF1B2A4A);
  static const navyDeep = Color(0xFF16233F);

  // --- Electric amber ---------------------------------------------------
  // From the logo. Primary actions and highlights ONLY — never the warning
  // colour, or a warning starts reading as a button.
  static const primary = Color(0xFFF5B400);
  static const primaryPressed = Color(0xFFD99F00);

  /// Text and icons placed ON [primary]. Navy, never white.
  ///
  /// White on amber fails contrast badly (about 1.9:1) and is the single most
  /// likely mistake in this palette. If something seems to need white text on
  /// amber, the answer is navy — not a lighter white.
  static const onPrimary = Color(0xFF16233F);

  // --- Text -------------------------------------------------------------
  static const textPrimary = Color(0xFF16233F);
  static const textSecondary = Color(0xFF5A6376);
  static const textDisabled = Color(0xFF9AA1AF);

  // --- Status -----------------------------------------------------------
  // warning is orange, deliberately distinct from the amber used for primary
  // actions, so a warning cannot be mistaken for something tappable.
  static const success = Color(0xFF1B9E4B);
  static const warning = Color(0xFFE8730A);
  static const error = Color(0xFFD32F2F);
}

/// Spacing scale. Screens use these rather than raw numbers so the rhythm
/// stays consistent and a future adjustment is one edit.
abstract final class AppSpacing {
  static const xs = 4.0;
  static const sm = 8.0;
  static const md = 12.0;
  static const lg = 16.0;
  static const xl = 24.0;
  static const xxl = 32.0;
}

/// Corner radius scale.
abstract final class AppRadius {
  static const sm = 8.0;
  static const md = 12.0;
  static const lg = 16.0;
}
