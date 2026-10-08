// process_tunel_40x.ijm
// TUNEL Assay - Strict Filename Pairing Workflow
setBatchMode(false);
setOption("BlackBackground", true);

args = getArgument();
args = replace(args, "\"", "");
argArray = split(args, "*");
inputDir = "";
csvPath = "";
signalStdDevMultiplier = 0.75;

if (lengthOf(args) == 0) {
    inputDir = getDirectory("Select Folder Containing DAPI and TUNEL TIF Files");
    if (inputDir == "") exit("No directory selected");
    csvPath = inputDir + "results.csv";
} else {
    inputDir = argArray[0];
    if (argArray.length >= 2) csvPath = argArray[1];
    if (argArray.length >= 3) signalStdDevMultiplier = parseFloat(argArray[2]);
}

inputDir = replace(inputDir, "\\", "/");
if (!endsWith(inputDir, "/")) inputDir = inputDir + "/";
csvPath = replace(csvPath, "\\", "/");

qcDir = inputDir + "qc_masks/";
noBrainDir = inputDir + "no_brain/";
File.makeDirectory(qcDir);
File.makeDirectory(noBrainDir);

if (!File.exists(csvPath)) {
    File.saveString("Label,DAPI_Image,TUNEL_Image,Area_brain_um2,Mean_Brain_Intensity,Area_signal_um2,MSI,IFI,NIFI,Status\n", csvPath);
}

scale40x = 5.5556; // pixels per um
fileList = getFileList(inputDir);
pairCount = 0;

print("--- SCANNING FOLDER FOR DAPI & TUNEL PAIRS ---");

for (i = 0; i < fileList.length; i++) {
    fileName = fileList[i];
    fileNameLow = toLowerCase(fileName);

    // Only initiate processing from DAPI files to maintain a 1:1 loop
    if (!File.isDirectory(inputDir + fileName) && 
        (endsWith(fileNameLow, ".tif") || endsWith(fileNameLow, ".tiff") || endsWith(fileNameLow, ".jpg") || endsWith(fileNameLow, ".png")) && 
        indexOf(fileNameLow, "_qc_mask") == -1 &&
        (indexOf(fileNameLow, "dapi") != -1)) {

        dapiFileName = fileName;
        tunelFileName = "";

        // Derive matching TUNEL filename by swapping tag names
        tunelFileName = replace(dapiFileName, "dapi", "tunel");
        if (!File.exists(inputDir + tunelFileName)) tunelFileName = replace(dapiFileName, "DAPI", "TUNEL");
        if (!File.exists(inputDir + tunelFileName)) tunelFileName = replace(dapiFileName, "Dapi", "Tunel");

        if (tunelFileName == "" || !File.exists(inputDir + tunelFileName)) {
            print("WARNING: DAPI file found (" + dapiFileName + "), but matching TUNEL file (" + tunelFileName + ") could not be located.");
            continue;
        }

        pairCount++;
        print("MATCHED PAIR #" + pairCount + ": [DAPI] " + dapiFileName + " <---> [TUNEL] " + tunelFileName);

        // ==========================================
        // STEP 1: Process DAPI Image (Visible to User)
        // ==========================================
        open(inputDir + dapiFileName);
        dapiID = getImageID();
        
        run("8-bit");
        run("Set Scale...", "distance=" + scale40x + " known=1 unit=um");
        
        setTool("freehand");
        waitForUser("Select Brain Region", "DAPI Image: " + dapiFileName + "\n\n1. Outline the BRAIN on this DAPI image.\n2. IF NO BRAIN: Click outside to DESELECT.\n3. Click OK.");

        if (selectionType() == -1) {
            // No Brain Route
            File.copy(inputDir + dapiFileName, noBrainDir + dapiFileName);
            File.copy(inputDir + tunelFileName, noBrainDir + tunelFileName);
            rowStr = dapiFileName + "," + dapiFileName + "," + tunelFileName + ",0,0,0,0,0,0,No Brain\n";
            File.append(rowStr, csvPath);
            close();
            continue;
        }

        // Store Brain ROI in ROI Manager
        roiManager("reset");
        roiManager("add");
        roiManager("select", 0);
        roiManager("rename", "Brain_ROI");

        // Save DAPI QC Mask (Red brain outline on DAPI image)
        run("Select None");
        roiManager("select", 0);
        Overlay.remove();
        Overlay.addSelection("red", 2);
        run("Flatten");
        saveAs("PNG", qcDir + dapiFileName + "_DAPI_QC_mask.png");
        close(); // Close DAPI flattened PNG mask
        
        selectImage(dapiID);
        close(); // Close DAPI original image

        // ==========================================
        // STEP 2: Process TUNEL Image (Batch Mode)
        // ==========================================
        setBatchMode(true);

        open(inputDir + tunelFileName);
        tunelID = getImageID();
        
        run("8-bit");
        run("Set Scale...", "distance=" + scale40x + " known=1 unit=um");

        // Measure Brain Region on TUNEL using the DAPI coordinates
        roiManager("select", 0); 
        getStatistics(brainArea, meanBrainInt, minBrainInt, maxBrainInt, stdDevBrainInt);

        // Duplicate TUNEL for threshold processing
        run("Select None");
        run("Duplicate...", "title=tunelWork");
        tunelWorkID = getImageID();

        roiManager("select", 0);
        setBackgroundColor(0, 0, 0);
        run("Clear Outside");
        run("Select None");

        run("Median...", "radius=1"); // Remove noise
        rawCutoff = meanBrainInt + (signalStdDevMultiplier * stdDevBrainInt);
        if (rawCutoff > 255) rawCutoff = 255;
        if (rawCutoff < 0) rawCutoff = 0;

        setThreshold(rawCutoff, 255);
        run("Create Selection");

        signalArea = 0; MSI = 0; IFI = 0; hasSignal = false;

        if (selectionType() != -1) {
            // Measure actual positive signal on the ORIGINAL TUNEL image
            selectImage(tunelID);
            run("Restore Selection");
            getStatistics(tempArea, tempMeanInt);

            if (tempArea > 0 && tempArea <= brainArea) {
                hasSignal = true;
                signalArea = tempArea;
                MSI = tempMeanInt;
                IFI = signalArea * MSI;
            }
        }

        if (isNaN(signalArea)) signalArea = 0;
        if (isNaN(MSI)) MSI = 0;
        if (isNaN(IFI)) IFI = 0;

        NIFI = 0;
        if (brainArea > 0) NIFI = IFI / brainArea;

        // Save TUNEL QC Mask (Red brain outline + Cyan TUNEL signal on TUNEL image)
        selectImage(tunelID);
        run("Select None");
        Overlay.remove();
        
        roiManager("select", 0);
        Overlay.addSelection("red", 2);
        
        if (hasSignal) {
            run("Restore Selection");
            Overlay.addSelection("cyan", 1);
        }
        
        run("Flatten");
        saveAs("PNG", qcDir + tunelFileName + "_TUNEL_QC_mask.png");
        
        // Write results to CSV
        rowStr = dapiFileName + "," + dapiFileName + "," + tunelFileName + "," + d2s(brainArea, 3) + "," + d2s(meanBrainInt, 3) + "," + d2s(signalArea, 3) + "," + d2s(MSI, 3) + "," + d2s(IFI, 3) + "," + d2s(NIFI, 6) + ",Processed\n";
        File.append(rowStr, csvPath);

        // Clean up memory
        while (nImages() > 0) close();
        roiManager("reset");
        setBatchMode(false);
    }
}

print("Scan Complete. Processed " + pairCount + " pair(s).");
if (pairCount == 0) print("ERROR: No matching DAPI/TUNEL file pairs were found in the folder.");
run("Quit");