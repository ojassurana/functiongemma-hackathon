import { Audio } from 'expo-av';
import * as LocalAuthentication from 'expo-local-authentication';
import { useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
} from 'react-native';

export default function HomeScreen() {
  const [apiBaseUrl, setApiBaseUrl] = useState('http://127.0.0.1:8000');
  const [recording, setRecording] = useState<Audio.Recording | null>(null);
  const [audioUri, setAudioUri] = useState<string | null>(null);
  const [transcript, setTranscript] = useState('');
  const [biometricOk, setBiometricOk] = useState<boolean | null>(null);
  const [plan, setPlan] = useState<any>(null);
  const [execution, setExecution] = useState<any>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function startRecording() {
    try {
      setError(null);
      const perm = await Audio.requestPermissionsAsync();
      if (!perm.granted) {
        setError('Microphone permission denied.');
        return;
      }
      await Audio.setAudioModeAsync({ allowsRecordingIOS: true, playsInSilentModeIOS: true });
      const created = await Audio.Recording.createAsync(Audio.RecordingOptionsPresets.HIGH_QUALITY);
      setRecording(created.recording);
      setAudioUri(null);
    } catch (err) {
      setRecording(null);
      setError(err instanceof Error ? err.message : 'Could not start recording.');
    }
  }

  async function stopRecording() {
    try {
      if (!recording) return;
      await recording.stopAndUnloadAsync();
      const uri = recording.getURI();
      setAudioUri(uri ?? null);
      setRecording(null);
      await Audio.setAudioModeAsync({ allowsRecordingIOS: false, playsInSilentModeIOS: true });
    } catch (err) {
      setRecording(null);
      setError(err instanceof Error ? err.message : 'Could not stop recording.');
    }
  }

  async function toggleRecording() {
    if (recording) {
      await stopRecording();
      return;
    }
    await startRecording();
  }

  async function runBiometric() {
    const hasHardware = await LocalAuthentication.hasHardwareAsync();
    const enrolled = await LocalAuthentication.isEnrolledAsync();
    if (!hasHardware || !enrolled) {
      setBiometricOk(false);
      return false;
    }
    const result = await LocalAuthentication.authenticateAsync({
      promptMessage: 'Verify payment',
      disableDeviceFallback: false,
    });
    setBiometricOk(result.success);
    return result.success;
  }

  async function transcribeVoice() {
    if (!audioUri && transcript.length === 0) {
      const fallback = 'send $20 to Alice';
      setTranscript(fallback);
      return fallback;
    }
    const resp = await fetch(`${apiBaseUrl}/transcribe`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        transcript_hint: transcript.length > 0 ? transcript : 'send $20 to Alice',
      }),
    });
    const data = await resp.json();
    const nextTranscript = String(data.transcript ?? '');
    setTranscript(nextTranscript);
    return nextTranscript;
  }

  async function planAndExecute() {
    setError(null);
    setIsBusy(true);
    setExecution(null);
    try {
      const bio = await runBiometric();
      const spokenText = await transcribeVoice();
      const planResp = await fetch(`${apiBaseUrl}/pay/plan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          transcript: spokenText,
          payment_context: {
            biometric_strong: bio,
          },
        }),
      });
      const planData = await planResp.json();
      setPlan(planData);

      const executeResp = await fetch(`${apiBaseUrl}/pay/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          function_calls: planData.function_calls ?? [],
          payment_context: { biometric_strong: bio },
        }),
      });
      const execData = await executeResp.json();
      setExecution(execData);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.');
    } finally {
      setIsBusy(false);
    }
  }

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.title}>VoicePay Demo</Text>
        <Text style={styles.subtitle}>Local-first voice payment with cloud fallback</Text>

        <Text style={styles.label}>Backend URL (use your Mac LAN IP on iPhone)</Text>
        <TextInput style={styles.input} value={apiBaseUrl} onChangeText={setApiBaseUrl} />

        <Pressable
          style={[styles.button, recording ? styles.buttonSecondary : styles.buttonPrimary]}
          onPress={toggleRecording}
          disabled={isBusy}
        >
          <Text style={styles.buttonText}>{recording ? 'Recording: ON (Tap to OFF)' : 'Recording: OFF (Tap to ON)'}</Text>
        </Pressable>
        <Pressable
          style={[styles.button, isBusy ? styles.buttonDisabled : styles.buttonPrimary]}
          onPress={planAndExecute}
          disabled={isBusy}
        >
          <Text style={styles.buttonText}>Run Payment Plan + Execute</Text>
        </Pressable>

        {isBusy ? <ActivityIndicator size="small" /> : null}

        <Text style={styles.label}>Transcript</Text>
        <TextInput
          style={[styles.input, styles.textArea]}
          multiline
          value={transcript}
          onChangeText={setTranscript}
          placeholder="Speak or type: send $25 to Alex"
        />

        <Text style={styles.label}>Biometric status</Text>
        <Text style={styles.value}>
          {biometricOk === null ? 'Not checked yet' : biometricOk ? 'Verified' : 'Failed / unavailable'}
        </Text>

        <Text style={styles.label}>Routing + plan</Text>
        <Text style={styles.value}>{plan ? JSON.stringify(plan, null, 2) : 'No plan yet'}</Text>

        <Text style={styles.label}>Execution</Text>
        <Text style={styles.value}>{execution ? JSON.stringify(execution, null, 2) : 'No execution yet'}</Text>

        {error ? (
          <>
            <Text style={styles.label}>Error</Text>
            <Text style={[styles.value, styles.error]}>{error}</Text>
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0b0f18',
  },
  content: {
    gap: 10,
    padding: 16,
  },
  title: {
    color: '#f8fafc',
    fontSize: 28,
    fontWeight: '700',
  },
  subtitle: {
    color: '#94a3b8',
    marginBottom: 4,
  },
  label: {
    color: '#cbd5e1',
    fontSize: 13,
    marginTop: 8,
  },
  input: {
    backgroundColor: '#1e293b',
    color: '#f8fafc',
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  textArea: {
    minHeight: 72,
    textAlignVertical: 'top',
  },
  row: {
    flexDirection: 'row',
    gap: 8,
  },
  button: {
    borderRadius: 8,
    paddingVertical: 12,
    alignItems: 'center',
  },
  buttonPrimary: {
    backgroundColor: '#2563eb',
  },
  buttonSecondary: {
    backgroundColor: '#d97706',
  },
  buttonDisabled: {
    backgroundColor: '#334155',
  },
  buttonText: {
    color: '#fff',
    fontWeight: '600',
  },
  value: {
    backgroundColor: '#111827',
    color: '#e2e8f0',
    borderRadius: 8,
    padding: 10,
    fontFamily: 'Courier',
    fontSize: 12,
  },
  error: {
    color: '#fca5a5',
  },
});
