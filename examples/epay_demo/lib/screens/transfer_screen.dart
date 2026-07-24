import 'package:flutter/material.dart';

import '../api.dart';
import '../theme.dart';

class TransferScreen extends StatefulWidget {
  const TransferScreen({super.key, required this.fromUserId});
  final String fromUserId;

  @override
  State<TransferScreen> createState() => _TransferScreenState();
}

class _TransferScreenState extends State<TransferScreen> {
  final _amount = TextEditingController();
  final _note = TextEditingController();
  List<WalletHolder> _holders = const [];
  String? _recipient;
  String? _error;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _amount.dispose();
    _note.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final holders = await walletApi.holders();
      if (mounted) {
        setState(
          () => _holders = holders
              .where((h) => h.userId != widget.fromUserId)
              .toList(),
        );
      }
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    }
  }

  Future<void> _send() async {
    final value = double.tryParse(_amount.text.trim());
    if (_recipient == null) {
      setState(() => _error = 'Select who you want to pay.');
      return;
    }
    if (value == null || value <= 0) {
      setState(() => _error = 'Enter an amount greater than zero.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await walletApi.transfer(
        fromUserId: widget.fromUserId,
        toUserId: _recipient!,
        amountCents: (value * 100).round(),
        note: _note.text.trim(),
      );
      if (mounted) Navigator.of(context).pop(true);
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Send money')),
    body: SafeArea(
      child: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Text(
            'Make a transfer',
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          const SizedBox(height: 6),
          const Text(
            'Choose a verified wallet and enter the payment details.',
            style: TextStyle(color: PayColors.muted),
          ),
          const SizedBox(height: 24),
          DropdownButtonFormField<String>(
            initialValue: _recipient,
            decoration: const InputDecoration(
              labelText: 'Recipient',
              prefixIcon: Icon(Icons.person_outline_rounded),
            ),
            items: _holders
                .map(
                  (holder) => DropdownMenuItem(
                    value: holder.userId,
                    child: Text(
                      holder.displayName,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                )
                .toList(),
            onChanged: (value) => setState(() => _recipient = value),
          ),
          const SizedBox(height: 14),
          TextField(
            controller: _amount,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: const InputDecoration(
              labelText: 'Amount',
              prefixIcon: Icon(Icons.payments_outlined),
              suffixText: 'USD',
            ),
          ),
          const SizedBox(height: 14),
          TextField(
            controller: _note,
            maxLength: 80,
            decoration: const InputDecoration(
              labelText: 'Note (optional)',
              prefixIcon: Icon(Icons.edit_note_rounded),
            ),
          ),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 14),
              child: Text(
                _error!,
                style: const TextStyle(color: PayColors.danger),
              ),
            ),
          FilledButton.icon(
            onPressed: _busy ? null : _send,
            icon: _busy
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: Colors.white,
                    ),
                  )
                : const Icon(Icons.arrow_forward_rounded),
            label: Text(_busy ? 'Sending securely…' : 'Review and send'),
          ),
          if (_holders.isEmpty)
            const Padding(
              padding: EdgeInsets.only(top: 16),
              child: Text(
                'No other verified wallets are available yet.',
                textAlign: TextAlign.center,
                style: TextStyle(color: PayColors.muted),
              ),
            ),
        ],
      ),
    ),
  );
}
