import 'package:flutter/material.dart';

class PayColors {
  static const sky = Color(0xFF1997E3);
  static const skyDark = Color(0xFF0877BC);
  static const skySoft = Color(0xFFEAF7FF);
  static const canvas = Color(0xFFF5FAFD);
  static const ink = Color(0xFF102A43);
  static const muted = Color(0xFF5C7184);
  static const line = Color(0xFFD9E7F0);
  static const success = Color(0xFF178B68);
  static const danger = Color(0xFFD64545);
}

// Backwards-compatible aliases used by a few demo widgets.
class KyronColors {
  static const navy = PayColors.ink;
  static const navyCard = Colors.white;
  static const gold = PayColors.sky;
  static const goldSoft = PayColors.skyDark;
  static const mint = PayColors.success;
  static const coral = PayColors.danger;
  static const textDim = PayColors.muted;
}

ThemeData buildKyronTheme() {
  final scheme = ColorScheme.fromSeed(
    seedColor: PayColors.sky,
    brightness: Brightness.light,
    primary: PayColors.sky,
    surface: Colors.white,
    error: PayColors.danger,
  );
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: PayColors.canvas,
    fontFamily: 'SF Pro Display',
    textTheme: const TextTheme(
      headlineLarge: TextStyle(
        fontSize: 32,
        fontWeight: FontWeight.w800,
        color: PayColors.ink,
      ),
      headlineSmall: TextStyle(
        fontSize: 23,
        fontWeight: FontWeight.w700,
        color: PayColors.ink,
      ),
      titleLarge: TextStyle(
        fontSize: 18,
        fontWeight: FontWeight.w700,
        color: PayColors.ink,
      ),
      bodyLarge: TextStyle(fontSize: 16, height: 1.45, color: PayColors.ink),
      bodyMedium: TextStyle(fontSize: 14, height: 1.45, color: PayColors.muted),
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: Colors.white,
      foregroundColor: PayColors.ink,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      centerTitle: false,
      titleTextStyle: TextStyle(
        fontSize: 18,
        fontWeight: FontWeight.w700,
        color: PayColors.ink,
      ),
    ),
    cardTheme: const CardThemeData(
      color: Colors.white,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.all(Radius.circular(8)),
        side: BorderSide(color: PayColors.line),
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: PayColors.sky,
        foregroundColor: Colors.white,
        minimumSize: const Size.fromHeight(54),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: PayColors.skyDark,
        side: const BorderSide(color: PayColors.line),
        minimumSize: const Size.fromHeight(54),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: Colors.white,
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(8),
        borderSide: const BorderSide(color: PayColors.line),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(8),
        borderSide: const BorderSide(color: PayColors.line),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(8),
        borderSide: const BorderSide(color: PayColors.sky, width: 2),
      ),
      labelStyle: const TextStyle(color: PayColors.muted),
    ),
    dividerColor: PayColors.line,
    progressIndicatorTheme: const ProgressIndicatorThemeData(
      color: PayColors.sky,
    ),
  );
}
