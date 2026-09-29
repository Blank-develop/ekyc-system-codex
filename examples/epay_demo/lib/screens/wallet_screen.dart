import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../api.dart';
import '../theme.dart';
import 'transfer_screen.dart';

class WalletScreen extends StatefulWidget {
  const WalletScreen({super.key, required this.userId});

  final String userId;

  @override
  State<WalletScreen> createState() => _WalletScreenState();
}

class _WalletScreenState extends State<WalletScreen> {
  Wallet? _wallet;
  String? _error;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    try {
      final wallet = await walletApi.wallet(widget.userId);
      if (mounted) {
        setState(() {
          _wallet = wallet;
          _error = null;
        });
      }
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    }
  }

  String _money(int cents, String currency) {
    final value = NumberFormat.currency(
      symbol: '',
      decimalDigits: 2,
    ).format(cents / 100).trim();
    return '$value $currency';
  }

  Future<void> _openTransfer() async {
    final wallet = _wallet;
    if (wallet == null) return;
    final sent = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => TransferScreen(fromUserId: wallet.userId),
      ),
    );
    if (sent == true) _refresh();
  }

  @override
  Widget build(BuildContext context) {
    final wallet = _wallet;
    return Scaffold(
      appBar: AppBar(
        title: const Text('CloudPay'),
        actions: [
          IconButton(
            tooltip: 'Refresh',
            onPressed: _refresh,
            icon: const Icon(Icons.refresh_rounded),
          ),
          IconButton(
            tooltip: 'Sign out',
            onPressed: () =>
                Navigator.of(context).popUntil((route) => route.isFirst),
            icon: const Icon(Icons.logout_rounded),
          ),
        ],
      ),
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: _refresh,
          child: ListView(
            padding: const EdgeInsets.fromLTRB(20, 12, 20, 28),
            children: [
              Row(
                children: [
                  CircleAvatar(
                    radius: 22,
                    backgroundColor: PayColors.skySoft,
                    child: Text(
                      (wallet?.displayName ?? 'U')
                          .trim()
                          .substring(0, 1)
                          .toUpperCase(),
                      style: const TextStyle(
                        color: PayColors.skyDark,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          'Good day',
                          style: TextStyle(
                            color: PayColors.muted,
                            fontSize: 13,
                          ),
                        ),
                        Text(
                          wallet?.displayName ?? widget.userId,
                          style: Theme.of(context).textTheme.titleLarge,
                        ),
                      ],
                    ),
                  ),
                  const Icon(
                    Icons.notifications_none_rounded,
                    color: PayColors.ink,
                  ),
                ],
              ),
              const SizedBox(height: 22),
              Container(
                padding: const EdgeInsets.all(22),
                decoration: BoxDecoration(
                  color: PayColors.sky,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Row(
                      children: [
                        Text(
                          'Available balance',
                          style: TextStyle(
                            color: Colors.white70,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        Spacer(),
                        Icon(
                          Icons.shield_outlined,
                          color: Colors.white70,
                          size: 20,
                        ),
                      ],
                    ),
                    const SizedBox(height: 14),
                    Text(
                      wallet == null
                          ? '—'
                          : _money(wallet.balanceCents, wallet.currency),
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 32,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    const SizedBox(height: 12),
                    Text(
                      'Wallet ID  ${widget.userId}',
                      style: const TextStyle(
                        color: Colors.white70,
                        fontSize: 12,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 18),
              Row(
                children: [
                  Expanded(
                    child: _QuickAction(
                      icon: Icons.north_east_rounded,
                      label: 'Send',
                      onTap: wallet == null ? null : _openTransfer,
                    ),
                  ),
                  const SizedBox(width: 10),
                  const Expanded(
                    child: _QuickAction(
                      icon: Icons.south_west_rounded,
                      label: 'Receive',
                    ),
                  ),
                  const SizedBox(width: 10),
                  const Expanded(
                    child: _QuickAction(
                      icon: Icons.qr_code_scanner_rounded,
                      label: 'Scan',
                    ),
                  ),
                ],
              ),
              if (_error != null) ...[
                const SizedBox(height: 16),
                _MessageBox(message: _error!),
              ],
              const SizedBox(height: 28),
              Row(
                children: [
                  Text(
                    'Recent activity',
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                  const Spacer(),
                  TextButton(onPressed: _refresh, child: const Text('Refresh')),
                ],
              ),
              const SizedBox(height: 8),
              if (wallet == null)
                const Center(
                  child: Padding(
                    padding: EdgeInsets.all(36),
                    child: CircularProgressIndicator(),
                  ),
                )
              else if (wallet.transactions.isEmpty)
                const Card(
                  child: Padding(
                    padding: EdgeInsets.all(24),
                    child: Text(
                      'Your payments will appear here.',
                      textAlign: TextAlign.center,
                    ),
                  ),
                )
              else
                Card(
                  child: Column(
                    children: [
                      for (
                        var index = 0;
                        index < wallet.transactions.length;
                        index++
                      ) ...[
                        _TransactionTile(
                          tx: wallet.transactions[index],
                          currency: wallet.currency,
                        ),
                        if (index < wallet.transactions.length - 1)
                          const Divider(height: 1, indent: 62),
                      ],
                    ],
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _QuickAction extends StatelessWidget {
  const _QuickAction({required this.icon, required this.label, this.onTap});
  final IconData icon;
  final String label;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) => InkWell(
    onTap: onTap,
    borderRadius: BorderRadius.circular(8),
    child: Container(
      height: 80,
      decoration: BoxDecoration(
        color: Colors.white,
        border: Border.all(color: PayColors.line),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(
            icon,
            color: onTap == null ? PayColors.muted : PayColors.skyDark,
          ),
          const SizedBox(height: 7),
          Text(
            label,
            style: const TextStyle(
              fontWeight: FontWeight.w700,
              color: PayColors.ink,
            ),
          ),
        ],
      ),
    ),
  );
}

class _TransactionTile extends StatelessWidget {
  const _TransactionTile({required this.tx, required this.currency});
  final WalletTransaction tx;
  final String currency;

  @override
  Widget build(BuildContext context) {
    final incoming = tx.amountCents >= 0;
    final title = switch (tx.kind) {
      'seed' => 'Opening balance',
      'transfer_in' => 'From ${tx.counterparty}',
      _ => 'To ${tx.counterparty}',
    };
    final amount = NumberFormat.currency(
      symbol: '',
      decimalDigits: 2,
    ).format(tx.amountCents.abs() / 100).trim();
    return ListTile(
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
      leading: CircleAvatar(
        backgroundColor: incoming ? const Color(0xFFE7F7F1) : PayColors.skySoft,
        child: Icon(
          incoming ? Icons.south_west_rounded : Icons.north_east_rounded,
          color: incoming ? PayColors.success : PayColors.skyDark,
          size: 20,
        ),
      ),
      title: Text(
        title,
        style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700),
      ),
      subtitle: Text(
        tx.note?.isNotEmpty == true ? tx.note! : 'Completed',
        style: const TextStyle(fontSize: 12),
      ),
      trailing: Text(
        '${incoming ? '+' : '-'}$amount',
        style: TextStyle(
          fontWeight: FontWeight.w800,
          color: incoming ? PayColors.success : PayColors.ink,
        ),
      ),
    );
  }
}

class _MessageBox extends StatelessWidget {
  const _MessageBox({required this.message});
  final String message;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(
      color: const Color(0xFFFFF1F1),
      border: Border.all(color: const Color(0xFFF3BABA)),
      borderRadius: BorderRadius.circular(8),
    ),
    child: Text(message, style: const TextStyle(color: PayColors.danger)),
  );
}
