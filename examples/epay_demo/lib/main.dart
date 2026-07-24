import 'package:flutter/material.dart';

import 'screens/home_screen.dart';
import 'theme.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const KyronPayApp());
}

class KyronPayApp extends StatelessWidget {
  const KyronPayApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'KyronPay',
      debugShowCheckedModeBanner: false,
      theme: buildKyronTheme(),
      home: const HomeScreen(),
    );
  }
}
