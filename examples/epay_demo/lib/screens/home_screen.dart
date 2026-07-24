import 'package:flutter/material.dart';

import '../theme.dart';
import 'face_login_screen.dart';
import 'register_screen.dart';

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.white,
      body: SafeArea(
        child: LayoutBuilder(
          builder: (context, constraints) {
            final width = constraints.maxWidth > 560
                ? 480.0
                : constraints.maxWidth;
            return SingleChildScrollView(
              child: Center(
                child: SizedBox(
                  width: width,
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(24, 28, 24, 20),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        const _BrandMark(),
                        const SizedBox(height: 34),
                        Container(
                          height: 164,
                          decoration: BoxDecoration(
                            color: PayColors.skySoft,
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: const Stack(
                            alignment: Alignment.center,
                            children: [
                              Icon(
                                Icons.account_balance_wallet_rounded,
                                size: 84,
                                color: PayColors.sky,
                              ),
                              Positioned(
                                right: 78,
                                top: 35,
                                child: _SecurityBadge(),
                              ),
                            ],
                          ),
                        ),
                        const SizedBox(height: 32),
                        Text(
                          'Money made simple.',
                          style: Theme.of(context).textTheme.headlineLarge,
                        ),
                        const SizedBox(height: 10),
                        Text(
                          'Create your wallet, send money securely, and return with a quick face scan.',
                          style: Theme.of(context).textTheme.bodyLarge
                              ?.copyWith(color: PayColors.muted),
                        ),
                        const SizedBox(height: 34),
                        FilledButton.icon(
                          icon: const Icon(Icons.person_add_alt_1_rounded),
                          label: const Text('Create an account'),
                          onPressed: () => Navigator.of(context).push(
                            MaterialPageRoute(
                              builder: (_) => const RegisterScreen(),
                            ),
                          ),
                        ),
                        const SizedBox(height: 12),
                        OutlinedButton.icon(
                          icon: const Icon(Icons.face_rounded),
                          label: const Text('Sign in with face'),
                          onPressed: () => Navigator.of(context).push(
                            MaterialPageRoute(
                              builder: (_) => const FaceLoginScreen(),
                            ),
                          ),
                        ),
                        const SizedBox(height: 22),
                        const Text(
                          'Identity verification secured by Kyron API',
                          textAlign: TextAlign.center,
                          style: TextStyle(
                            color: PayColors.muted,
                            fontSize: 12,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            );
          },
        ),
      ),
    );
  }
}

class _BrandMark extends StatelessWidget {
  const _BrandMark();

  @override
  Widget build(BuildContext context) => const Row(
    children: [
      DecoratedBox(
        decoration: BoxDecoration(
          color: PayColors.sky,
          borderRadius: BorderRadius.all(Radius.circular(8)),
        ),
        child: SizedBox(
          width: 42,
          height: 42,
          child: Icon(Icons.payments_rounded, color: Colors.white),
        ),
      ),
      SizedBox(width: 12),
      Text(
        'CloudPay',
        style: TextStyle(
          fontSize: 21,
          fontWeight: FontWeight.w800,
          color: PayColors.ink,
        ),
      ),
    ],
  );
}

class _SecurityBadge extends StatelessWidget {
  const _SecurityBadge();

  @override
  Widget build(BuildContext context) => Container(
    width: 42,
    height: 42,
    decoration: const BoxDecoration(
      color: PayColors.success,
      shape: BoxShape.circle,
    ),
    child: const Icon(
      Icons.verified_user_rounded,
      color: Colors.white,
      size: 22,
    ),
  );
}
