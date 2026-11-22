// Lab Matter thermostat that behaves like an IKEA LILJEBAGGE (heating only, child lock).
// Run: node thermostat.mjs   (or scripts/lab-thermostat.sh). Lab only.
import { homedir } from "node:os";
import { join } from "node:path";
import { Endpoint, Environment, ServerNode, StorageService, VendorId } from "@matter/main";
import { ThermostatDevice } from "@matter/main/devices";
import { ThermostatServer } from "@matter/main/behaviors/thermostat";
import { ThermostatUserInterfaceConfigurationServer } from "@matter/main/behaviors/thermostat-user-interface-configuration";
import { IdentifyServer } from "@matter/main/behaviors/identify";
import { Thermostat } from "@matter/main/clusters/thermostat";

const labHome = process.env.LAB_HOME ?? join(homedir(), ".matter-explorer-lab");
const storage = process.env.LAB_THERMOSTAT_STORAGE ?? (process.env.LAB_THERMOSTAT_N && process.env.LAB_THERMOSTAT_N !== "1" ? join(labHome, `thermostat-${process.env.LAB_THERMOSTAT_N}`) : join(labHome, "thermostat"));
const env = Environment.default;
env.vars.set("storage.path", storage);

// A second instance: LAB_THERMOSTAT_N=2 -> id lab-thermostat-2, code 20202025, discriminator 3845, port 5542
const N = process.env.LAB_THERMOSTAT_N ?? "1";
const second = N !== "1";
const NAME = second ? `lab-thermostat-${N}` : "lab-thermostat";
const PASSCODE = second ? 20202024 + Number(N) - 1 : 20202024;
const DISCRIMINATOR = second ? 3844 + Number(N) - 1 : 3844;
const PORT = second ? 5541 + Number(N) - 1 : 5541;

const HeatingThermostat = ThermostatServer.with("Heating");

const node = await ServerNode.create({
    id: NAME,
    network: { port: PORT },
    commissioning: { passcode: PASSCODE, discriminator: DISCRIMINATOR },
    productDescription: { name: "LILJEBAGGE radiator thermostat", deviceType: ThermostatDevice.deviceType },
    basicInformation: {
        vendorName: "IKEA of Sweden",
        // 4476 (IKEA) makes the Matter Server demand the test-net DCL option (test DAC); use the test vendor id
        vendorId: VendorId(0xfff1),
        productName: "LILJEBAGGE radiator thermostat",
        productId: 0x8000,
        nodeLabel: second ? `Lab thermostat ${N}` : "Lab thermostat",
        hardwareVersion: 515,
        hardwareVersionString: "P2.3",
        softwareVersion: 16842758,
        softwareVersionString: "1.1.6",
        serialNumber: `LAB-THERMOSTAT-${N}`,
        uniqueId: `lab-thermostat-000${N}`,
    },
});

const endpoint = new Endpoint(
    ThermostatDevice.with(HeatingThermostat, ThermostatUserInterfaceConfigurationServer, IdentifyServer),
    {
        id: "thermostat",
        identify: { identifyTime: 0, identifyType: 2 },
        thermostat: {
            localTemperature: 1950,
            occupiedHeatingSetpoint: 2100,
            absMinHeatSetpointLimit: 500,
            absMaxHeatSetpointLimit: 3500,
            minHeatSetpointLimit: 500,
            maxHeatSetpointLimit: 3500,
            controlSequenceOfOperation: Thermostat.ControlSequenceOfOperation.HeatingOnly,
            systemMode: Thermostat.SystemMode.Heat,
        },
        thermostatUserInterfaceConfiguration: {
            temperatureDisplayMode: 0,
            keypadLockout: 1, // the real device has the child lock on level 1
        },
    },
);
await node.add(endpoint);

console.log(`Lab thermostat starting; setup code ${PASSCODE}, discriminator ${DISCRIMINATOR}, port ${PORT}`);
await node.run();
