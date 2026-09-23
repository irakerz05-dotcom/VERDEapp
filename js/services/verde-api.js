// Development-only adapter. Replace this class with a Raspberry Pi API client later.
export class MockVerdeApi {
  async getSnapshot() {
    return {
      online: true,
      mode: "Full Automation",
      updatedAt: new Date().toISOString(),
      sensors: [
        { label: "pH", value: "5.9", unit: "", status: "Optimal", icon: "◈" },
        { label: "EC", value: "1.5", unit: "mS/cm", status: "Optimal", icon: "⌁" },
        { label: "Water Temperature", value: "22.1", unit: "°C", status: "Optimal", icon: "♨" },
        { label: "Turbidity", value: "3.2", unit: "NTU", status: "Optimal", icon: "≋" },
        { label: "Ambient Humidity", value: "72", unit: "%", status: "Normal", icon: "◌" }
      ],
      waterQuality: "Optimal",
      plant: { condition: "Healthy", pest: false, confidence: "92%" },
      fusion: { confidence: "High", reason: "Sensor readings and plant condition agree." },
      alerts: []
    };
  }

  async requestModeChange(mode) {
    // Future implementation: POST to a backend endpoint that validates safety state.
    return { accepted: true, mode };
  }
}
