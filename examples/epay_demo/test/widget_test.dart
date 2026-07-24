import 'package:flutter_test/flutter_test.dart';

import 'package:kyronpay_demo/main.dart';

void main() {
  testWidgets('home screen shows register and face login actions', (
    tester,
  ) async {
    await tester.pumpWidget(const KyronPayApp());
    expect(find.text('CloudPay'), findsOneWidget);
    expect(find.text('Create an account'), findsOneWidget);
    expect(find.text('Sign in with face'), findsOneWidget);
  });
}
