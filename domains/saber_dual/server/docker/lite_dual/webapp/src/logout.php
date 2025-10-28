<?php
session_start();

// Simple logout
session_destroy();
header("Location: /");
exit();
?>