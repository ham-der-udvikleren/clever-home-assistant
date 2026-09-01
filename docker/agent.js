import Java from "frida-java-bridge";

Java.perform(function () {
    // Suppress the unrelated Google Play Services Maps-SDK-dynamite background-thread crash
    // (NoClassDefFoundError: org.apache.http.ProtocolVersion) so the app stays alive and keeps
    // streaming live Firestore updates instead of dying and needing a full relaunch every time.
    try {
        var Thread = Java.use("java.lang.Thread");
        Thread.dispatchUncaughtException.implementation = function (ex) {
            send("SUPPRESSED uncaught exception on thread '" + this.getName() + "': " + ex);
        };
        send("Hooked Thread.dispatchUncaughtException (crash suppression)");
    } catch (e) {
        send("Could not hook Thread.dispatchUncaughtException: " + e);
    }

    // Only the domain objects we actually consume - SmartChargingFlow/CpmsChargingStatus were
    // always null in practice, and the FirebaseFirestore.collection()/document() hooks fire on
    // every listener re-subscription (very hot path) for zero runtime value - dropped both to
    // minimize JNI hook overhead racing the ART concurrent GC (root cause of HeapTaskDaemon SIGSEGVs).
    var targets = [
        "dk.clever.data.transaction.domain.ActiveTransaction",
        "dk.clever.data.transaction.domain.ChargingPlan",
        "dk.clever.data.transaction.domain.VehicleStateOfCharge",
    ];

    targets.forEach(function (className) {
        try {
            var Cls = Java.use(className);
            Cls.$init.overloads.forEach(function (overload) {
                overload.implementation = function () {
                    var ret = overload.apply(this, arguments);
                    // Must call toString() synchronously here - the Java object wrapper is only
                    // valid within this JNI call frame; deferring via setImmediate/setTimeout
                    // uses a stale reference and segfaults (art::JNI::CallObjectMethod crash).
                    try {
                        send(className + " => " + this.toString());
                    } catch (e) {
                        send(className + " toString() failed: " + e);
                    }
                    return ret;
                };
            });
            send("Hooked " + className + " (" + Cls.$init.overloads.length + " ctor overloads)");
        } catch (e) {
            send("Could not hook " + className + ": " + e);
        }
    });
});

