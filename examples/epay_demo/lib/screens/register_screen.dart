import 'dart:async';

import 'package:camera/camera.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:laligence_ekyc/laligence_ekyc.dart';

import '../api.dart';
import '../theme.dart';
import 'wallet_screen.dart';

enum _OnboardingStep { account, document, liveness, gesture, selfie, finishing }

class RegisterScreen extends StatefulWidget {
  const RegisterScreen({super.key});

  @override
  State<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends State<RegisterScreen> {
  final _userId = TextEditingController();
  CameraController? _camera;
  VerificationResult? _result;
  _OnboardingStep _step = _OnboardingStep.account;
  bool _busy = false;
  String? _message;
  String? _error;

  @override
  void dispose() {
    _userId.dispose();
    _camera?.dispose();
    super.dispose();
  }

  Future<void> _setCamera(CameraLensDirection direction) async {
    await _camera?.dispose();
    _camera = null;
    if (mounted) setState(() {});
    final cameras = await availableCameras();
    final selected = cameras.firstWhere(
      (camera) => camera.lensDirection == direction,
      orElse: () => cameras.first,
    );
    final controller = CameraController(
      selected,
      ResolutionPreset.high,
      enableAudio: false,
    );
    await controller.initialize();
    if (!mounted) {
      await controller.dispose();
      return;
    }
    setState(() => _camera = controller);
  }

  Future<void> _begin() async {
    final id = _userId.text.trim();
    if (id.length < 4) {
      setState(() => _error = 'Create a user ID with at least 4 characters.');
      return;
    }
    await _run(
      () async {
        _result = await ekyc.createVerification(id);
        _step = _OnboardingStep.document;
        _message =
            'Photograph the original passport. Keep all four edges visible.';
      },
      fallback:
          'We could not reach the identity service. Check the server address and connection.',
    );
    if (_result != null && mounted) {
      await _prepareDocumentCamera();
    }
  }

  Future<void> _prepareDocumentCamera() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await _setCamera(CameraLensDirection.back);
    } on CameraException catch (error) {
      if (mounted) {
        setState(
          () => _error = error.code == 'CameraAccessDenied'
              ? 'Camera access is blocked. Allow CloudPay in System Settings > Privacy & Security > Camera, then select Retry camera.'
              : 'The document camera could not start (${error.code}). Close other camera apps and retry.',
        );
      }
    } catch (_) {
      if (mounted) {
        setState(
          () => _error =
              'The document camera could not start. Close other camera apps and select Retry camera.',
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _captureDocument() async {
    final camera = _camera;
    if (camera == null) return;
    await _run(
      () async {
        final shot = await camera.takePicture();
        await _analyzeDocument(
          EkycUpload.fromBytes(
            await shot.readAsBytes(),
            filename: 'passport.jpg',
          ),
        );
      },
      fallback:
          'The document could not be verified. Retake it in brighter, even light.',
    );
    if (_step == _OnboardingStep.liveness && mounted) {
      await _prepareFrontCamera();
    }
  }

  Future<void> _uploadDocument() async {
    final selection = await FilePicker.pickFiles(
      type: FileType.image,
      withData: true,
    );
    final file = selection?.files.single;
    if (file == null) return;
    final upload = file.bytes != null
        ? EkycUpload.fromBytes(file.bytes!, filename: file.name)
        : EkycUpload.fromPath(file.path!, filename: file.name);
    await _run(
      () => _analyzeDocument(upload),
      fallback:
          'The selected document could not be verified. Choose a clear JPG or PNG image.',
    );
    if (_step == _OnboardingStep.liveness && mounted) {
      await _prepareFrontCamera();
    }
  }

  Future<void> _analyzeDocument(EkycUpload upload) async {
    final result = _result;
    if (result == null) throw StateError('Verification session is missing.');
    final updated = await ekyc.uploadDocument(result.sessionId, upload);
    _result = updated;
    if (updated.document.status != UploadStatus.passed) {
      throw StateError(
        _friendlyReasons(
          updated.reasonCodes,
          'The document needs another image. Use even light and avoid glare.',
        ),
      );
    }
    _step = _OnboardingStep.liveness;
    _message =
        'Now confirm that you are present. Follow each action naturally.';
  }

  Future<void> _prepareFrontCamera() async {
    try {
      await _setCamera(CameraLensDirection.front);
    } catch (_) {
      if (mounted) {
        setState(
          () => _error =
              'The front camera is required for the live-face step. Allow camera access, then retry.',
        );
      }
    }
  }

  Future<List<EkycUpload>> _captureBurst(String prefix, {int count = 3}) async {
    final camera = _camera;
    if (camera == null) throw StateError('Camera is not ready.');
    final frames = <EkycUpload>[];
    for (var index = 0; index < count; index++) {
      if (index > 0) {
        await Future<void>.delayed(const Duration(milliseconds: 260));
      }
      final shot = await camera.takePicture();
      frames.add(
        EkycUpload.fromBytes(
          await shot.readAsBytes(),
          filename: '$prefix-$index.jpg',
        ),
      );
    }
    return frames;
  }

  Future<void> _verifyActiveChallenge() async {
    final result = _result;
    if (result == null) return;
    final challenge = result.activeChallenges
        .where((item) => !item.passed)
        .firstOrNull;
    if (challenge == null) {
      setState(() => _step = _OnboardingStep.gesture);
      return;
    }
    await _run(
      () async {
        final frames = await _captureBurst(challenge.id);
        final updated = await ekyc.completeActiveLiveness(
          result.sessionId,
          challenge.id,
          frames,
        );
        _result = updated;
        if (!updated.activeChallenges.any(
          (item) => item.id == challenge.id && item.passed,
        )) {
          throw StateError(
            _friendlyReasons(
              updated.reasonCodes,
              'We could not confirm that action. Move closer and try again.',
            ),
          );
        }
        if (updated.biometric.activeLivenessPassed) {
          _step = _OnboardingStep.gesture;
          _message =
              'Complete the three hand prompts to protect this enrollment.';
        }
      },
      fallback:
          'The live check was not clear. Move closer, face even light, and repeat the action.',
    );
  }

  Future<void> _uploadActiveTestFrames() async {
    final result = _result;
    final challenge = result?.activeChallenges
        .where((item) => !item.passed)
        .firstOrNull;
    if (result == null || challenge == null) return;
    final selection = await FilePicker.pickFiles(
      type: FileType.image,
      allowMultiple: true,
      withData: true,
    );
    if (selection == null) return;
    final frames = selection.files.take(3).map(_platformUpload).toList();
    if (frames.isEmpty) return;
    await _run(() async {
      final updated = await ekyc.completeActiveLiveness(
        result.sessionId,
        challenge.id,
        frames,
      );
      _result = updated;
      if (!updated.activeChallenges.any(
        (item) => item.id == challenge.id && item.passed,
      )) {
        throw StateError(
          _friendlyReasons(
            updated.reasonCodes,
            'The selected test frames did not pass liveness analysis.',
          ),
        );
      }
      if (updated.biometric.activeLivenessPassed) {
        _step = _OnboardingStep.gesture;
        _message =
            'Complete the three hand prompts to protect this enrollment.';
      }
    }, fallback: 'The selected test frames could not be analyzed.');
  }

  Future<void> _confirmGesture() async {
    final result = _result;
    if (result == null) return;
    final challenge = result.handChallenges
        .where((item) => !item.passed)
        .firstOrNull;
    if (challenge == null) {
      setState(() => _step = _OnboardingStep.selfie);
      return;
    }
    await _run(
      () async {
        final updated = await ekyc.completeChallenge(
          result.sessionId,
          challenge.id,
          nonce: challenge.nonce,
        );
        _result = updated;
        if (updated.biometric.handChallengePassed) {
          _step = _OnboardingStep.selfie;
          _message =
              'One final live selfie will be matched with your document.';
        }
      },
      fallback:
          'The gesture could not be confirmed. Hold your hand clearly in view and try again.',
    );
  }

  Future<void> _captureSelfieAndFinish() async {
    final result = _result;
    final camera = _camera;
    if (result == null || camera == null) return;
    await _run(
      () async {
        _step = _OnboardingStep.finishing;
        final shot = await camera.takePicture();
        await _finishWithSelfie(
          EkycUpload.fromBytes(
            await shot.readAsBytes(),
            filename: 'selfie.jpg',
          ),
        );
      },
      fallback:
          'Account setup could not be completed. Retake the selfie and try again.',
    );
  }

  Future<void> _uploadSelfieTestImage() async {
    final selection = await FilePicker.pickFiles(
      type: FileType.image,
      withData: true,
    );
    final file = selection?.files.single;
    if (file == null) return;
    await _run(() async {
      _step = _OnboardingStep.finishing;
      await _finishWithSelfie(_platformUpload(file));
    }, fallback: 'The selected selfie could not be analyzed.');
  }

  Future<void> _finishWithSelfie(EkycUpload upload) async {
    final result = _result;
    if (result == null) throw StateError('Verification session is missing.');
    final analyzed = await ekyc.analyzeSelfie(result.sessionId, upload);
    _result = analyzed;
    if (analyzed.decision != Decision.passed) {
      _step = _OnboardingStep.selfie;
      throw StateError(
        _friendlyReasons(
          analyzed.reasonCodes,
          'The selfie was not accepted. Center your face and use even light.',
        ),
      );
    }
    await ekyc.enrollFace(analyzed.sessionId);
    final wallet = await walletApi.claim(analyzed.userId);
    if (!mounted) return;
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(builder: (_) => WalletScreen(userId: wallet.userId)),
    );
  }

  EkycUpload _platformUpload(PlatformFile file) {
    if (file.bytes != null) {
      return EkycUpload.fromBytes(file.bytes!, filename: file.name);
    }
    if (file.path != null) {
      return EkycUpload.fromPath(file.path!, filename: file.name);
    }
    throw StateError('The selected file could not be read.');
  }

  Future<void> _run(
    Future<void> Function() action, {
    required String fallback,
  }) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await action();
    } catch (error) {
      if (mounted) {
        setState(() => _error = error is StateError ? error.message : fallback);
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  String _friendlyReasons(List<String> reasons, String fallback) {
    if (reasons.any(
      (code) => code.contains('REPLAY') || code.contains('SPOOF'),
    )) {
      return 'A screen or photo may be present. Use your real face directly and remove other displays.';
    }
    if (reasons.any(
      (code) => code.contains('BLUR') || code.contains('QUALITY'),
    )) {
      return 'The capture is not clear enough. Hold steady and improve the lighting.';
    }
    return fallback;
  }

  int get _stepIndex => switch (_step) {
    _OnboardingStep.account => 0,
    _OnboardingStep.document => 1,
    _OnboardingStep.liveness => 2,
    _OnboardingStep.gesture => 3,
    _OnboardingStep.selfie || _OnboardingStep.finishing => 4,
  };

  Challenge? get _currentChallenge {
    final result = _result;
    if (result == null) return null;
    if (_step == _OnboardingStep.liveness) {
      return result.activeChallenges.where((item) => !item.passed).firstOrNull;
    }
    if (_step == _OnboardingStep.gesture) {
      return result.handChallenges.where((item) => !item.passed).firstOrNull;
    }
    return null;
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Create account')),
    body: SafeArea(
      child: LayoutBuilder(
        builder: (context, constraints) => Center(
          child: SizedBox(
            width: constraints.maxWidth > 680 ? 560 : constraints.maxWidth,
            child: ListView(
              padding: const EdgeInsets.fromLTRB(20, 10, 20, 28),
              children: [
                _ProgressHeader(current: _stepIndex),
                const SizedBox(height: 24),
                Text(_title, style: Theme.of(context).textTheme.headlineSmall),
                const SizedBox(height: 6),
                Text(
                  _description,
                  style: const TextStyle(color: PayColors.muted, height: 1.45),
                ),
                if (_message != null)
                  Container(
                    margin: const EdgeInsets.only(top: 16),
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: PayColors.skySoft,
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Row(
                      children: [
                        const Icon(
                          Icons.info_outline_rounded,
                          color: PayColors.skyDark,
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Text(
                            _message!,
                            style: const TextStyle(color: PayColors.skyDark),
                          ),
                        ),
                      ],
                    ),
                  ),
                const SizedBox(height: 20),
                if (_step == _OnboardingStep.account)
                  _accountForm()
                else
                  _cameraPanel(),
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
                _primaryAction(),
                const SizedBox(height: 14),
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
                      'Identity checks processed securely by Kyron API',
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

  String get _title => switch (_step) {
    _OnboardingStep.account => 'Set up your wallet',
    _OnboardingStep.document => 'Verify your document',
    _OnboardingStep.liveness => _currentChallenge?.prompt ?? 'Live face check',
    _OnboardingStep.gesture => _currentChallenge?.prompt ?? 'Hand check',
    _OnboardingStep.selfie => 'Match your selfie',
    _OnboardingStep.finishing => 'Creating your wallet',
  };

  String get _description => switch (_step) {
    _OnboardingStep.account =>
      'Choose an ID for this demo wallet. Your identity will be verified before the account opens.',
    _OnboardingStep.document =>
      'Use the back camera and photograph the original passport data page.',
    _OnboardingStep.liveness =>
      _currentChallenge?.instruction ?? 'Follow the action shown on screen.',
    _OnboardingStep.gesture =>
      _currentChallenge?.instruction ??
          'Show the requested hand gesture clearly.',
    _OnboardingStep.selfie =>
      'Look directly at the camera. We will compare this live selfie with your document portrait.',
    _OnboardingStep.finishing =>
      'Please wait while we secure your Face ID and prepare the wallet.',
  };

  Widget _accountForm() => Column(
    children: [
      TextField(
        controller: _userId,
        autocorrect: false,
        decoration: const InputDecoration(
          labelText: 'User ID',
          prefixIcon: Icon(Icons.person_outline_rounded),
          hintText: 'e.g. savath-pay',
        ),
        onSubmitted: (_) => _begin(),
      ),
      const SizedBox(height: 12),
      const Card(
        child: Padding(
          padding: EdgeInsets.all(16),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(Icons.verified_user_outlined, color: PayColors.success),
              SizedBox(width: 12),
              Expanded(
                child: Text(
                  'You will need an original passport and access to the front and back cameras.',
                ),
              ),
            ],
          ),
        ),
      ),
    ],
  );

  Widget _cameraPanel() => AspectRatio(
    aspectRatio: _step == _OnboardingStep.document ? 4 / 3 : 4 / 5,
    child: ClipRRect(
      borderRadius: BorderRadius.circular(8),
      child: ColoredBox(
        color: PayColors.skySoft,
        child: _camera == null
            ? Center(
                child: _busy
                    ? const CircularProgressIndicator()
                    : const Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(
                            Icons.no_photography_outlined,
                            size: 48,
                            color: PayColors.muted,
                          ),
                          SizedBox(height: 10),
                          Text(
                            'Camera is not ready',
                            style: TextStyle(color: PayColors.muted),
                          ),
                        ],
                      ),
              )
            : Stack(
                fit: StackFit.expand,
                children: [
                  CameraPreview(_camera!),
                  if (_step == _OnboardingStep.document)
                    Center(
                      child: FractionallySizedBox(
                        widthFactor: .9,
                        heightFactor: .62,
                        child: DecoratedBox(
                          decoration: BoxDecoration(
                            border: Border.all(color: Colors.white, width: 3),
                            borderRadius: BorderRadius.circular(8),
                          ),
                        ),
                      ),
                    ),
                  if (_step == _OnboardingStep.finishing)
                    const ColoredBox(
                      color: Color(0x99FFFFFF),
                      child: Center(child: CircularProgressIndicator()),
                    ),
                ],
              ),
      ),
    ),
  );

  Widget _primaryAction() {
    if (_step == _OnboardingStep.document) {
      return Column(
        children: [
          FilledButton.icon(
            onPressed: _busy
                ? null
                : (_camera == null ? _prepareDocumentCamera : _captureDocument),
            icon: Icon(
              _camera == null
                  ? Icons.refresh_rounded
                  : Icons.document_scanner_outlined,
            ),
            label: Text(_camera == null ? 'Retry camera' : 'Capture passport'),
          ),
          const SizedBox(height: 10),
          OutlinedButton.icon(
            onPressed: _busy ? null : _uploadDocument,
            icon: const Icon(Icons.upload_file_rounded),
            label: const Text('Upload passport image'),
          ),
        ],
      );
    }
    if (_step == _OnboardingStep.liveness && _camera == null) {
      return Column(
        children: [
          FilledButton.icon(
            onPressed: _busy ? null : _uploadActiveTestFrames,
            icon: const Icon(Icons.science_outlined),
            label: const Text('Select test frames'),
          ),
          const SizedBox(height: 8),
          const Text(
            'Simulator testing only — select up to 3 pre-captured frames of the requested action.',
            textAlign: TextAlign.center,
            style: TextStyle(color: PayColors.muted, fontSize: 12),
          ),
        ],
      );
    }
    if (_step == _OnboardingStep.selfie && _camera == null) {
      return Column(
        children: [
          FilledButton.icon(
            onPressed: _busy ? null : _uploadSelfieTestImage,
            icon: const Icon(Icons.science_outlined),
            label: const Text('Select test selfie'),
          ),
          const SizedBox(height: 8),
          const Text(
            'Simulator testing only — production enrollment requires a live camera.',
            textAlign: TextAlign.center,
            style: TextStyle(color: PayColors.muted, fontSize: 12),
          ),
        ],
      );
    }
    final (icon, label, action) = switch (_step) {
      _OnboardingStep.account => (
        Icons.arrow_forward_rounded,
        'Start identity check',
        _begin,
      ),
      _OnboardingStep.document => (Icons.upload_file_rounded, 'Upload', null),
      _OnboardingStep.liveness => (
        Icons.face_rounded,
        'I performed the action',
        _verifyActiveChallenge,
      ),
      _OnboardingStep.gesture => (
        Icons.back_hand_outlined,
        'Verify gesture',
        _confirmGesture,
      ),
      _OnboardingStep.selfie => (
        Icons.camera_alt_outlined,
        'Capture and create wallet',
        _captureSelfieAndFinish,
      ),
      _OnboardingStep.finishing => (
        Icons.hourglass_top_rounded,
        'Finishing…',
        null,
      ),
    };
    return FilledButton.icon(
      onPressed: _busy ? null : action,
      icon: _busy
          ? const SizedBox(
              width: 18,
              height: 18,
              child: CircularProgressIndicator(
                strokeWidth: 2,
                color: Colors.white,
              ),
            )
          : Icon(icon),
      label: Text(label),
    );
  }
}

class _ProgressHeader extends StatelessWidget {
  const _ProgressHeader({required this.current});
  final int current;

  @override
  Widget build(BuildContext context) => Row(
    children: [
      for (var index = 0; index < 5; index++) ...[
        Expanded(
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 220),
            height: 5,
            decoration: BoxDecoration(
              color: index <= current ? PayColors.sky : PayColors.line,
              borderRadius: BorderRadius.circular(3),
            ),
          ),
        ),
        if (index < 4) const SizedBox(width: 6),
      ],
    ],
  );
}
