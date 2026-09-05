import 'package:flutter/material.dart';

import 'app_colors.dart';

/// The one VOLT theme, shared by both apps (spec 016).
///
/// Light only, by decision — it matches the logo and reads in daylight, and
/// one theme is cheaper to keep coherent than two. A dark variant is a real
/// want (drivers work at night) and is recorded in docs/future-plans.md.
///
/// The colour scheme is written out rather than derived from
/// `ColorScheme.fromSeed`, which invents tonal values that drift from the
/// sampled palette — the previous theme seeded from navy and produced a
/// purple-ish secondary nothing in the logo resembles.
ThemeData buildVoltTheme() {
  const scheme = ColorScheme(
    brightness: Brightness.light,
    primary: AppColors.primary,
    onPrimary: AppColors.onPrimary,
    primaryContainer: AppColors.primary,
    onPrimaryContainer: AppColors.onPrimary,
    secondary: AppColors.navy,
    onSecondary: Colors.white,
    secondaryContainer: AppColors.navy,
    onSecondaryContainer: Colors.white,
    surface: AppColors.surface,
    onSurface: AppColors.textPrimary,
    surfaceContainerHighest: AppColors.surfaceSunken,
    onSurfaceVariant: AppColors.textSecondary,
    outline: AppColors.border,
    outlineVariant: AppColors.border,
    error: AppColors.error,
    onError: Colors.white,
    errorContainer: AppColors.error,
    onErrorContainer: Colors.white,
  );

  final textTheme = _buildTextTheme();

  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: AppColors.background,
    textTheme: textTheme,

    // Platform font, deliberately. google_fonts' runtime fetch is forbidden
    // by this spec — a delivery app that renders wrong until it has network
    // is a bad trade for a typeface — and nothing is bundled, so Roboto on
    // Android is what ships. A well-set default beats a badly-set custom face.
    fontFamily: null,

    appBarTheme: const AppBarTheme(
      backgroundColor: AppColors.navy,
      foregroundColor: Colors.white,
      elevation: 0,
      scrolledUnderElevation: 0,
      centerTitle: false,
      // The one place white-on-navy is correct. Everywhere else, text on a
      // brand colour is navy-on-amber.
      titleTextStyle: TextStyle(
        color: Colors.white,
        fontSize: 20,
        fontWeight: FontWeight.w600,
      ),
      iconTheme: IconThemeData(color: Colors.white),
    ),

    cardTheme: CardThemeData(
      color: AppColors.surface,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppRadius.md),
        side: const BorderSide(color: AppColors.border),
      ),
    ),

    dividerTheme: const DividerThemeData(
      color: AppColors.border,
      thickness: 1,
      space: 1,
    ),

    // Every primary action in both apps is a FilledButton — there are 22 of
    // them and zero ElevatedButtons. Both are themed identically so a future
    // ElevatedButton cannot render un-themed by accident.
    filledButtonTheme: FilledButtonThemeData(style: _primaryButtonStyle()),
    elevatedButtonTheme: ElevatedButtonThemeData(style: _primaryButtonStyle()),

    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: AppColors.navy,
        disabledForegroundColor: AppColors.textDisabled,
        minimumSize: const Size.fromHeight(52),
        side: const BorderSide(color: AppColors.navy, width: 1.5),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.md),
        ),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
      ),
    ),

    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: AppColors.navy,
        disabledForegroundColor: AppColors.textDisabled,
        textStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
      ),
    ),

    // Address entry is the most-used input in the app, so this is worth
    // getting right rather than leaving to defaults.
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: AppColors.surfaceSunken,
      contentPadding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.lg,
        vertical: 18,
      ),
      hintStyle: const TextStyle(color: AppColors.textDisabled, fontSize: 15),
      labelStyle: const TextStyle(color: AppColors.textSecondary),
      floatingLabelStyle: const TextStyle(color: AppColors.navy),
      prefixIconColor: AppColors.textSecondary,
      suffixIconColor: AppColors.textSecondary,
      border: _inputBorder(AppColors.border),
      enabledBorder: _inputBorder(AppColors.border),
      focusedBorder: _inputBorder(AppColors.navy, width: 2),
      errorBorder: _inputBorder(AppColors.error),
      focusedErrorBorder: _inputBorder(AppColors.error, width: 2),
      disabledBorder: _inputBorder(AppColors.border),
      errorStyle: const TextStyle(color: AppColors.error, fontSize: 13),
    ),

    snackBarTheme: SnackBarThemeData(
      backgroundColor: AppColors.navyDeep,
      contentTextStyle: const TextStyle(color: Colors.white, fontSize: 14),
      actionTextColor: AppColors.primary,
      behavior: SnackBarBehavior.floating,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppRadius.sm),
      ),
    ),

    // Dialogs and bottom sheets otherwise pick up Material defaults, which
    // read as a different app the moment one opens.
    dialogTheme: DialogThemeData(
      backgroundColor: AppColors.surface,
      surfaceTintColor: Colors.transparent,
      titleTextStyle: textTheme.titleLarge,
      contentTextStyle: textTheme.bodyMedium,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppRadius.lg),
      ),
    ),

    bottomSheetTheme: BottomSheetThemeData(
      backgroundColor: AppColors.surface,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(
          top: Radius.circular(AppRadius.lg),
        ),
      ),
    ),

    listTileTheme: const ListTileThemeData(
      iconColor: AppColors.textSecondary,
      textColor: AppColors.textPrimary,
    ),

    progressIndicatorTheme: const ProgressIndicatorThemeData(
      color: AppColors.navy,
    ),

    iconTheme: const IconThemeData(color: AppColors.navy),

    dropdownMenuTheme: const DropdownMenuThemeData(
      menuStyle: MenuStyle(
        backgroundColor: WidgetStatePropertyAll(AppColors.surface),
      ),
    ),
  );
}

/// Amber fill, navy label. Never amber with white text.
///
/// The disabled state is a real state rather than opacity: a faded amber
/// button still reads as amber, and on a phone in daylight "faded" is not a
/// signal anyone notices. Disabled goes to sunken grey with disabled text.
ButtonStyle _primaryButtonStyle() {
  return ButtonStyle(
    backgroundColor: WidgetStateProperty.resolveWith((states) {
      if (states.contains(WidgetState.disabled)) return AppColors.surfaceSunken;
      if (states.contains(WidgetState.pressed)) return AppColors.primaryPressed;
      return AppColors.primary;
    }),
    foregroundColor: WidgetStateProperty.resolveWith((states) {
      if (states.contains(WidgetState.disabled)) return AppColors.textDisabled;
      return AppColors.onPrimary;
    }),
    overlayColor: const WidgetStatePropertyAll(Colors.transparent),
    elevation: const WidgetStatePropertyAll(0),
    minimumSize: const WidgetStatePropertyAll(Size.fromHeight(52)),
    shape: WidgetStatePropertyAll(
      RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppRadius.md),
      ),
    ),
    side: WidgetStateProperty.resolveWith((states) {
      if (states.contains(WidgetState.disabled)) {
        return const BorderSide(color: AppColors.border);
      }
      return BorderSide.none;
    }),
    textStyle: const WidgetStatePropertyAll(
      TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
    ),
  );
}

OutlineInputBorder _inputBorder(Color colour, {double width = 1}) {
  return OutlineInputBorder(
    borderRadius: BorderRadius.circular(AppRadius.md),
    borderSide: BorderSide(color: colour, width: width),
  );
}

/// A real scale rather than Material defaults, which are tuned for a denser
/// information design than this app has.
TextTheme _buildTextTheme() {
  return const TextTheme(
    displaySmall: TextStyle(
      fontSize: 32,
      fontWeight: FontWeight.w700,
      color: AppColors.textPrimary,
      height: 1.2,
    ),
    headlineMedium: TextStyle(
      fontSize: 26,
      fontWeight: FontWeight.w700,
      color: AppColors.textPrimary,
      height: 1.25,
    ),
    headlineSmall: TextStyle(
      fontSize: 22,
      fontWeight: FontWeight.w700,
      color: AppColors.textPrimary,
      height: 1.3,
    ),
    titleLarge: TextStyle(
      fontSize: 20,
      fontWeight: FontWeight.w600,
      color: AppColors.textPrimary,
    ),
    titleMedium: TextStyle(
      fontSize: 17,
      fontWeight: FontWeight.w600,
      color: AppColors.textPrimary,
    ),
    titleSmall: TextStyle(
      fontSize: 15,
      fontWeight: FontWeight.w600,
      color: AppColors.textPrimary,
    ),
    bodyLarge: TextStyle(
      fontSize: 16,
      color: AppColors.textPrimary,
      height: 1.45,
    ),
    bodyMedium: TextStyle(
      fontSize: 14,
      color: AppColors.textPrimary,
      height: 1.45,
    ),
    bodySmall: TextStyle(
      fontSize: 13,
      color: AppColors.textSecondary,
      height: 1.4,
    ),
    labelLarge: TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
    labelMedium: TextStyle(
      fontSize: 13,
      fontWeight: FontWeight.w600,
      color: AppColors.textSecondary,
    ),
    labelSmall: TextStyle(
      fontSize: 11,
      fontWeight: FontWeight.w600,
      color: AppColors.textSecondary,
      letterSpacing: 0.5,
    ),
  );
}
