import 'dart:async';

import 'package:camera/camera.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:laligence_ekyc/laligence_ekyc.dart';

import '../api.dart';
import '../theme.dart';
import 'wallet_screen.dart';

class FaceLoginScreen extends StatefulWidget {
  const FaceLoginScreen({super.key});

  @override
  State<FaceLoginScreen> createState() => _FaceLoginScreenState();
}

class _FaceLoginScreenState extends State<FaceLoginScreen> {
  CameraController? _camera;
  bool _initializing = true;
  bool _capturing = false;
  String? _status;
  String? _error;

  @override
  void initState() {
    super.initState();
    _initCamera();
  }

  Future<void> _initCamera() async {
    try {
      final cameras = await availableCameras();
      final front = cameras.firstWhere(
        (camera) => camera.lensDirection == CameraLensDirection.front,
        orElse: () => cameras.first,
      );
      final controller = CameraController(
        front,
        ResolutionPreset.medium,
        enableAudio: false,
      );
      await controller.initialize();
      if (!mounted) {
        await controller.dispose();
        return;
      }
      setState(() {
        _camera = controller;
        _initializing = false;
      });
    } catch (error) {
      if (mounted) {
        setState(() {
          _initializing = false;
          _error = 'Camera unavailable. Check camera permission and try again.';
        });
      }
    }
  }

  @override
  void dispose() {
    _camera?.dispose();
    super.dispose();
  }

  Future<void> _login() async {
    final camera = _camera;
    if (camera == null || _capturing) return;
    setState(() {
      _capturing = true;
      _error = null;
      _status = 'Capturing a short live scan…';
    });
    try {
      final frames = <EkycUpload>[];
      for (var index = 0; index < 6; index += 1) {
        if (index > 0) {
          await Future<void>.delayed(const Duration(milliseconds: 220));
        }
        final shot = await camera.takePicture();
        frames.add(
          EkycUpload.fromBytes(
            await shot.readAsBytes(),
            filename: 'login-$index.jpg',
          ),
        );
      }
      if (mounted) setState(() => _status = 'Checking your identity…');
      final result = await ekyc.faceLoginBurst(frames);
      if (!mounted) return;
      if (result.matched && result.profile != null) {
        Navigator.of(context).pushReplacement(
          MaterialPageRoute(
            builder: (_) => WalletScreen(userId: result.profile!.userId),
          ),
        );
      } else {
        setState(() {
          _status = null;
          _error = result.reasonCodes.contains('FACE_LOGIN_LIVENESS_FAILED')
              ? 'We could not confirm a live face. Move closer, use even lighting, and try again.'
              : 'We could not find your wallet. Check your position or create an account first.';
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _status = null;
          _error =
              'Sign-in could not be completed. Check your connection and try again.';
        });
      }
    } finally {
      if (mounted) setState(() => _capturing = false);
    }
  }

  Future<void> _loginWithTestFrames() async {
    final selection = await FilePicker.pickFiles(
      type: FileType.image,
      allowMultiple: true,
      withData: true,
    );
    if (selection == null || selection.files.isEmpty) return;
    final frames = selection.files.take(6).map((file) {
      if (file.bytes != null) {
        return EkycUpload.fromBytes(file.bytes!, filename: file.name);
      }
      if (file.path != null) {
        return EkycUpload.fromPath(file.path!, filename: file.name);
      }
      throw StateError('The selected file could not be read.');
    }).toList();
    setState(() {
      _capturing = true;
      _error = null;
      _status = 'Checking selected test frames…';
    });
    try {
      final result = await ekyc.faceLoginBurst(frames);
      if (!mounted) return;
      if (result.matched && result.profile != null) {
        Navigator.of(context).pushReplacement(
          MaterialPageRoute(
            builder: (_) => WalletScreen(userId: result.profile!.userId),
          ),
        );
      } else {
        setState(() {
          _status = null;
          _error = 'The selected test frames did not match a verified wallet.';
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _status = null;
          _error = 'The selected test frames could not be analyzed.';
        });
      }
    } finally {
      if (mounted) setState(() => _capturing = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Face sign in')),
    body: SafeArea(
      child: LayoutBuilder(
        builder: (context, constraints) => Center(
          child: SizedBox(
            width: constraints.maxWidth > 620 ? 520 : constraints.maxWidth,
            child: ListView(
              padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
              children: [
                Text(
                  'Welcome back',
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
                const SizedBox(height: 6),
                const Text(
                  'Position your face clearly in the frame to open your wallet.',
                  style: TextStyle(color: PayColors.muted),
                ),
                const SizedBox(height: 22),
                AspectRatio(
                  aspectRatio: 4 / 5,
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(8),
                    child: ColoredBox(
                      color: PayColors.skySoft,
                      child: _initializing
                          ? const Center(child: CircularProgressIndicator())
                          : _camera == null
                          ? const Center(
                              child: Icon(
                                Icons.no_photography_outlined,
                                size: 56,
                                color: PayColors.muted,
                              ),
                            )
                          : Stack(
                              fit: StackFit.expand,
                              children: [
                                CameraPreview(_camera!),
                                Center(
                                  child: Container(
                                    width: 230,
                                    height: 290,
                                    decoration: BoxDecoration(
                                      border: Border.all(
                                        color: Colors.white,
                                        width: 3,
                                      ),
                                      borderRadius: BorderRadius.circular(115),
                                    ),
                                  ),
                                ),
                                const Positioned(
                                  left: 14,
                                  right: 14,
                                  bottom: 14,
                                  child: DecoratedBox(
                                    decoration: BoxDecoration(
                                      color: Color(0xCC102A43),
                                      borderRadius: BorderRadius.all(
                                        Radius.circular(8),
                                      ),
                                    ),
                                    child: Padding(
                                      padding: EdgeInsets.all(10),
                                      child: Text(
                                        'Keep your face centered and look at the camera',
                                        textAlign: TextAlign.center,
                                        style: TextStyle(color: Colors.white),
                                      ),
                                    ),
                                  ),
                                ),
                              ],
                            ),
                    ),
                  ),
                ),
                if (_status != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 14),
                    child: Text(
                      _status!,
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                        color: PayColors.skyDark,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                if (_error != null)
                  Container(
                    margin: const EdgeInsets.only(top: 14),
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(
                      color: const Color(0xFFFFF1F1),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Text(
                      _error!,
                      style: const TextStyle(color: PayColors.danger),
                    ),
                  ),
                const SizedBox(height: 16),
                FilledButton.icon(
                  onPressed: _capturing
                      ? null
                      : (_camera == null ? _loginWithTestFrames : _login),
                  icon: _capturing
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.white,
                          ),
                        )
                      : const Icon(Icons.face_rounded),
                  label: Text(
                    _capturing
                        ? 'Signing you in…'
                        : (_camera == null
                              ? 'Select test face frames'
                              : 'Continue with face'),
                  ),
                ),
                if (_camera == null) ...[
                  const SizedBox(height: 8),
                  const Text(
                    'Simulator testing only — production face login requires a live camera.',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: PayColors.muted, fontSize: 12),
                  ),
                ],
                const SizedBox(height: 12),
                const Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Icon(
                      Icons.lock_outline_rounded,
                      size: 16,
                      color: PayColors.muted,
                    ),
                    SizedBox(width: 6),
                    Text(
                      'Your scan is used only for identity verification',
                      style: TextStyle(color: PayColors.muted, fontSize: 12),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    ),
  );
}
