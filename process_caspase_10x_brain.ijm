// process_caspase_10x_semi.ijm
setBatchMode(false);
setOption("BlackBackground", true);

args = getArgument();
args = replace(args, "\"", "");
argArray = split(args, "*");
inputDir = argArray[0];
csvPath = argArray[1];

// Read Sensitivity Multiplier passed from Python or prompt if run standalone
signalStdDevMultiplier = 0.75;
if (argArray.length >= 3) {
    signalStdDevMultiplier = parseFloat(argArray[2]);
} else {
    Dialog.create("Signal Detection Sensitivity");
    Dialog.addNumber("Sensitivity Multiplier (Default 0.75):", 0.75);
    Dialog.show();
    signalStdDevMultiplier = Dialog.getNumber();
}

inputDir = replace(inputDir, "\\", "/");
if (!endsWith(inputDir, "/")) {
    inputDir = inputDir + "/";
}

qcDir = inputDir + "qc_masks/";
noBrainDir = inputDir + "no_brain/";
File.makeDirectory(qcDir);
File.makeDirectory(noBrainDir);

// Initialize fresh CSV Header with Status column
File.saveString("Label,Area_brain_um2,MeanOD_brain,MinOD_brain,MaxOD_brain,Area_signal_um2,MeanOD_signal,IOD,NIOD,RawIntDen_brain,Status\n", csvPath);

scale10x = 1.3870;

list = getFileList(inputDir);

for (i = 0; i < list.length; i++) {
    fileName = list[i];
    fileNameLow = toLowerCase(fileName);

    if ((endsWith(fileNameLow, ".tif") || endsWith(fileNameLow, ".tiff") || endsWith(fileNameLow, ".jpg") || endsWith(fileNameLow, ".png")) && !File.isDirectory(inputDir + fileName) && indexOf(fileNameLow, "_mask") == -1) {
        filePath = inputDir + fileName;

        open(filePath);
        origID = getImageID();
        run("8-bit");
        run("Set Scale...", "distance=" + scale10x + " known=1 unit=um");

        // Interactive Brain Selection
        setTool("freehand");
        waitForUser("Select Brain Region", "Image: " + fileName + "\n\n1. Outline the BRAIN region using Freehand.\n2. IF NO BRAIN: Click anywhere outside to DESELECT.\n3. Click OK when done.");

        // CHECK IF USER DREW A BRAIN REGION OR NOT
        if (selectionType() == -1) {
            // --- NO BRAIN IN IMAGE ---
            File.copy(filePath, noBrainDir + fileName);

            rowStr = fileName + ",0,0,0,0,0,0,0,0,0,No Brain\n";
            File.append(rowStr, csvPath);

        } else {
            // --- BRAIN PRESENT ---
            roiManager("reset");
            roiManager("add"); // Index 0: Brain ROI
            roiManager("select", 0);
            roiManager("rename", "Brain_ROI");

            // Calibrate OD on original image
            selectImage(origID);
            run("Calibrate...", "function=[Uncalibrated OD]");

            // Measure Brain ROI
            getStatistics(brainArea, meanOD, minOD, maxOD);
            getRawStatistics(brainNPix, brainRawMean, brainRawMin, brainRawMax, brainRawSD);
            rawIntDen = brainNPix * brainRawMean;

            // Signal Detection Duplicate
            selectImage(origID);
            run("Select None");
            run("Duplicate...", "title=sigWork");
            sigWorkID = getImageID();
            
            run("Calibrate...", "function=None");
            roiManager("select", 0);
            setBackgroundColor(255, 255, 255);
            run("Clear Outside");
            run("Select None");

            run("Median...", "radius=1");
            rawCutoff = brainRawMean - (signalStdDevMultiplier * brainRawSD);
            if (rawCutoff < 0) rawCutoff = 0;
            if (rawCutoff > 255) rawCutoff = 255;
            
            setThreshold(0, rawCutoff);
            run("Create Selection");

            signalArea = 0;
            signalMeanOD = 0;
            IOD = 0;
            hasSignal = false;

            if (selectionType() != -1) {
                selectImage(origID);
                run("Restore Selection");
                getStatistics(tempArea, tempMeanOD);

                if (tempArea > 0 && tempArea <= brainArea) {
                    hasSignal = true;
                    signalArea = tempArea;
                    signalMeanOD = tempMeanOD;
                    IOD = signalArea * signalMeanOD;
                }
            }

            if (isNaN(signalArea)) signalArea = 0;
            if (isNaN(signalMeanOD)) signalMeanOD = 0;
            if (isNaN(IOD)) IOD = 0;

            NIOD = 0;
            if (brainArea > 0) {
                NIOD = IOD / brainArea;
            }

            // Save QC Overlay
            selectImage(origID);
            run("Select None");
            roiManager("select", 0);
            Overlay.addSelection("red", 2); // Brain outline
            
            if (hasSignal) {
                run("Restore Selection");
                Overlay.addSelection("cyan", 1); // Signal outline
            }
            
            run("Flatten");
            saveAs("PNG", qcDir + fileName + "_QC_mask.png");
            close();

            if (isOpen(sigWorkID)) { selectImage(sigWorkID); close(); }

            // Append row to raw CSV
            rowStr = fileName + "," + d2s(brainArea, 3) + "," + d2s(meanOD, 6) + "," + d2s(minOD, 6) + "," + d2s(maxOD, 6) + "," + d2s(signalArea, 3) + "," + d2s(signalMeanOD, 6) + "," + d2s(IOD, 3) + "," + d2s(NIOD, 6) + "," + d2s(rawIntDen, 0) + ",Processed\n";
            File.append(rowStr, csvPath);
        }

        // Clean up open image windows
        if (isOpen("Results")) {
            selectWindow("Results");
            run("Close");
        }
        while (nImages() > 0) {
            selectImage(nImages());
            close();
        }
        roiManager("reset");
    }
}

// Automatically quit ImageJ when batch is done
run("Quit");